"""Collect Instituto Balseiro theses from RICABIB.

RICABIB (Repositorio Institucional del Centro Atomico Bariloche,
https://ricabib.cab.cnea.gov.ar) is an EPrints repository holding essentially
every IB thesis: physics degree ("Tesis de Licenciatura / Grado"), the
engineering "Proyecto Integrador", master's and doctoral theses. That makes it
the most authoritative *roster* of graduates -- but it has no current-employer
data, so people only found here appear on the map only once another source
(ORCID / OpenAlex / your manual CSV) supplies a location.

*** The repository is served from Argentina and is often unreachable from
    outside the country. Run this script from an Argentine connection. ***

    python3 scripts/collect_ricabib.py            # full harvest via OAI-PMH
    python3 scripts/collect_ricabib.py --limit 200
    python3 scripts/collect_ricabib.py --probe     # just test connectivity

Output: data/raw/ricabib_theses.json
"""
from __future__ import annotations

import re
import sys
import time
import xml.etree.ElementTree as ET

from common import RAW, SESSION

BASE = "https://ricabib.cab.cnea.gov.ar"
OAI = f"{BASE}/cgi/oai2"
NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

THESIS_TYPE_MAP = [
    (r"doctoral|doctorado|ph\.?d", "Doctoral thesis"),
    (r"maestr[ií]a|master", "Master's thesis"),
    (r"integrador|ingenier", "Engineering degree project"),
    (r"licenciatura|grado|f[ií]sica", "Physics degree thesis"),
]


def _get(url, params, tries=4):
    for i in range(tries):
        try:
            r = SESSION.get(url, params=params, timeout=45)
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry ({exc})")
            time.sleep(3 * (i + 1))
    return ""


def probe() -> bool:
    print(f"Probing {BASE} ...")
    try:
        txt = _get(OAI, {"verb": "Identify"}, tries=1)
        name = re.search(r"<repositoryName>(.*?)</repositoryName>", txt)
        print("  reachable:", name.group(1) if name else "yes (OAI-PMH responds)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  NOT reachable from here: {exc}")
        print("  -> run this script from an Argentine connection.")
        return False


def _classify_type(text: str) -> str | None:
    t = (text or "").lower()
    for pat, label in THESIS_TYPE_MAP:
        if re.search(pat, t):
            return label
    return None


def _flip_name(name: str) -> str:
    """'Perez, Juan Carlos' -> 'Juan Carlos Perez'."""
    name = re.sub(r"\s+", " ", name).strip()
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return name


def _parse_records(xml_text: str):
    root = ET.fromstring(xml_text)
    for rec in root.findall(".//oai:record", NS):
        md = rec.find(".//oai_dc:dc", NS)
        if md is None:
            continue

        def vals(tag):
            return [e.text.strip() for e in md.findall(f"dc:{tag}", NS)
                    if e.text and e.text.strip()]

        types = vals("type")
        title = (vals("title") or [None])[0]
        creators = vals("creator")
        subjects = vals("subject")
        dates = vals("date")
        ident = next((v for v in vals("identifier") if v.startswith("http")), None)

        blob = " ".join(types + subjects + vals("description"))
        if "tesis" not in blob.lower() and "thesis" not in blob.lower() \
           and not _classify_type(blob):
            continue

        year = None
        for d in dates:
            m = re.search(r"(19|20)\d{2}", d)
            if m:
                year = int(m.group()); break

        for c in creators or []:
            yield {
                "author": _flip_name(c),
                "year": year,
                "title": title,
                "degree_program": _classify_type(blob),
                "subjects": subjects[:6],
                "url": ident,
            }

    token = root.find(".//oai:resumptionToken", NS)
    return token.text if token is not None and token.text else None


def collect(limit: int | None = None) -> list[dict]:
    if not probe():
        return []

    out, token, page = [], None, 0
    while True:
        page += 1
        params = ({"verb": "ListRecords", "resumptionToken": token} if token
                  else {"verb": "ListRecords", "metadataPrefix": "oai_dc"})
        xml_text = _get(OAI, params)
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            print(f"  parse error on page {page}: {exc}")
            break

        err = root.find(".//oai:error", NS)
        if err is not None:
            print(f"  OAI error: {err.get('code')} {err.text}")
            break

        # re-walk (generator above also returns the token via StopIteration.value)
        gen = _parse_records(xml_text)
        try:
            while True:
                out.append(next(gen))
        except StopIteration as stop:
            token = stop.value

        print(f"  page {page}: {len(out)} thesis-author rows so far")
        time.sleep(0.5)
        if not token or (limit and len(out) >= limit):
            break

    # de-dup (same author + year + title)
    seen, uniq = set(), []
    for r in out:
        k = (r["author"].lower(), r["year"], (r["title"] or "").lower())
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    (RAW / "ricabib_theses.json").write_text(
        __import__("json").dumps(uniq, indent=1, ensure_ascii=False), encoding="utf-8")
    people = len({r["author"].lower() for r in uniq})
    print(f"RICABIB: {len(uniq)} theses, {people} distinct authors "
          f"-> data/raw/ricabib_theses.json")
    return uniq


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        lim = None
        if "--limit" in sys.argv:
            lim = int(sys.argv[sys.argv.index("--limit") + 1])
        collect(lim)
