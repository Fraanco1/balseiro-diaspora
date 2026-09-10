"""Shared helpers: HTTP with on-disk cache, Nominatim geocoding, name utilities."""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SITE_DATA = ROOT / "site" / "data"
RAW.mkdir(parents=True, exist_ok=True)
SITE_DATA.mkdir(parents=True, exist_ok=True)

USER_AGENT = "BalseiroAlumniMap/1.0 (personal research project; contact fraanco.borgarello@gmail.com)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

# Instituto Balseiro identifiers across sources.
WIKIDATA_QID = "Q3151718"
BALSEIRO_NAME_PATTERNS = [
    "instituto balseiro",
    "balseiro institute",
    "instituto balseiro",  # common misspelling in the wild
    "centro atomico bariloche",
    "centro atómico bariloche",
    "comision nacional de energia atomica",  # a few records list only the parent
]

_last_call: dict[str, float] = {}


def _throttle(key: str, min_interval: float) -> None:
    now = time.monotonic()
    wait = min_interval - (now - _last_call.get(key, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_call[key] = time.monotonic()


def cached_get(url, *, params=None, headers=None, cache_key=None,
               min_interval=1.0, throttle_key="default", ttl_days=30,
               expect="json"):
    """GET with a persistent cache under data/raw/. Returns parsed JSON or text."""
    key_src = cache_key or (url + "?" + json.dumps(params, sort_keys=True) if params else url)
    digest = hashlib.sha1(key_src.encode()).hexdigest()[:16]
    ext = "json" if expect == "json" else "txt"
    path = RAW / f"{throttle_key}_{digest}.{ext}"

    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_days * 86400:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw) if expect == "json" else raw

    _throttle(throttle_key, min_interval)
    hdrs = dict(headers or {})
    if expect == "json":
        hdrs.setdefault("Accept", "application/json")
    for attempt in range(4):
        try:
            resp = SESSION.get(url, params=params, headers=hdrs, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2 ** attempt * 2)
                continue
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt * 2)
    else:  # pragma: no cover
        raise RuntimeError(f"failed: {url}")

    if expect == "json":
        data = resp.json()
        path.write_text(json.dumps(data), encoding="utf-8")
        return data
    path.write_text(resp.text, encoding="utf-8")
    return resp.text


# --------------------------------------------------------------------------- #
# Geocoding
# --------------------------------------------------------------------------- #
_GEOCODE_CACHE = DATA / "geocode_cache.json"


def _load_geocache() -> dict:
    if _GEOCODE_CACHE.exists():
        return json.loads(_GEOCODE_CACHE.read_text(encoding="utf-8"))
    return {}


def _save_geocache(cache: dict) -> None:
    _GEOCODE_CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")


def geocode(query: str, *, cache: dict | None = None) -> dict | None:
    """Resolve a place/institution string to {lat, lon, display_name, country}.

    Uses a local cache first, then Nominatim (1 req/s, per their usage policy).
    Returns None when nothing is found; the miss is cached so we do not retry.
    """
    own_cache = cache is None
    cache = cache if cache is not None else _load_geocache()
    q = re.sub(r"\s+", " ", query).strip()
    if not q:
        return None
    if q in cache:
        hit = cache[q]
        if own_cache:
            pass
        return hit or None

    result = None
    try:
        data = cached_get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 1},
            throttle_key="nominatim", min_interval=1.1, ttl_days=180,
        )
        if data:
            top = data[0]
            result = {
                "lat": float(top["lat"]),
                "lon": float(top["lon"]),
                "display_name": top.get("display_name"),
                "country": (top.get("address") or {}).get("country"),
                "country_code": ((top.get("address") or {}).get("country_code") or "").upper(),
            }
    except Exception as exc:  # noqa: BLE001 - geocoding is best-effort
        print(f"  ! geocode error for {q!r}: {exc}")
        result = None

    cache[q] = result or {}
    if own_cache:
        _save_geocache(cache)
    return result


def geocode_many(queries, progress_every=25):
    """Geocode an iterable of strings, sharing one cache file."""
    cache = _load_geocache()
    out = {}
    todo = list(dict.fromkeys(queries))
    for i, q in enumerate(todo, 1):
        out[q] = geocode(q, cache=cache)
        if i % progress_every == 0:
            print(f"  geocoded {i}/{len(todo)}")
            _save_geocache(cache)
    _save_geocache(cache)
    return out


# --------------------------------------------------------------------------- #
# Name helpers (for dedupe across sources)
# --------------------------------------------------------------------------- #
def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def name_key(name: str) -> str:
    n = strip_accents(name or "").lower()
    n = re.sub(r"[^a-z\s-]", " ", n)
    parts = [p for p in re.split(r"[\s-]+", n) if p and p not in {"de", "del", "la", "el", "van", "von"}]
    parts.sort()
    return " ".join(parts)


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).title() if (name or "").isupper() else re.sub(r"\s+", " ", (name or "").strip())
