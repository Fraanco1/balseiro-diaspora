"""Find Balseiro alumni in the industry diaspora via patents (Lens.org).

Academic sources miss the graduates who went into industry -- but many of them
appear on patents. This collector doesn't try to search "Balseiro alumni"
(patents don't record that); instead it pulls patents filed by organisations
that are overwhelmingly staffed by Balseiro people:

  * INVAP           - the Bariloche high-tech company founded by IB graduates
  * CNEA / CONICET  - Argentina's atomic-energy commission & research council
  * Instituto Balseiro itself

and treats their inventors as likely alumni (confidence: inferred), recording
the assignee as their employer and their residence country as their location.

*** Requires a free Lens.org API token. *** Register for "Lens.org for
Researchers" at https://www.lens.org, then Profile -> Toolkit -> Access Tokens.
Put it in the environment (preferred) or a gitignored file:

    export LENS_TOKEN=xxxxxxxx           # or: data/lens_token.txt

Never commit the token (this repo is public); regenerate it in Lens if it leaks.
Without a token this collector does nothing.

Output: data/raw/lens_inventors.json
"""
from __future__ import annotations

import json
import os
import re
import time

from common import RAW, DATA, SESSION, strip_accents

API = "https://api.lens.org/patent/search"

APPLICANTS = [
    "INVAP",
    "Comisión Nacional de Energía Atómica",
    "Comision Nacional de Energia Atomica",
    "National Atomic Energy Commission",
    "Consejo Nacional de Investigaciones Científicas y Técnicas",
    "Instituto Balseiro",
    "Centro Atómico Bariloche",
]

COUNTRY_BY_CODE = {
    "AR": "Argentina", "US": "United States", "BR": "Brazil", "DE": "Germany",
    "ES": "Spain", "FR": "France", "GB": "United Kingdom", "NL": "Netherlands",
    "CH": "Switzerland", "IT": "Italy", "CA": "Canada", "MX": "Mexico",
    "CL": "Chile", "SE": "Sweden", "BE": "Belgium", "AU": "Australia",
}


def _token() -> str | None:
    tok = os.environ.get("LENS_TOKEN", "").strip()
    if tok:
        return tok
    f = DATA / "lens_token.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def _flip(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "")).strip().strip(",")
    if "," in name:
        fam, giv = name.split(",", 1)
        name = f"{giv.strip()} {fam.strip()}"
    return re.sub(r"\s+", " ", name).strip()


def _looks_like_person(name: str) -> bool:
    n = strip_accents(name or "")
    if not n or len(n.split()) < 2:
        return False
    org_words = ("inc", "ltd", "llc", "gmbh", "s.a", "corp", "comisión", "comision",
                 "university", "universidad", "institut", "consejo", "company",
                 "laborator", "technolog", "invap", "cnea", "conicet")
    return not any(w in n.lower() for w in org_words)


def collect() -> list[dict]:
    tok = _token()
    if not tok:
        print("Lens: no API token (set LENS_TOKEN or create data/lens_token.txt) — "
              "skipping. See scripts/collect_lens.py header.")
        (RAW / "lens_inventors.json").write_text("[]", encoding="utf-8")
        return []

    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    people: dict[str, dict] = {}
    for applicant in APPLICANTS:
        body = {
            "query": {"match_phrase": {"applicant.name": applicant}},
            "size": 100, "scroll": "1m",
            "include": ["lens_id", "biblio.invention_title.title",
                        "biblio.parties.applicants.extracted_name.value",
                        "biblio.parties.inventors.extracted_name.value",
                        "biblio.parties.inventors.residence", "date_published"],
        }
        scroll_id = None
        pages = 0
        while pages < 15:
            payload = {"scroll_id": scroll_id, "scroll": "1m"} if scroll_id else body
            try:
                r = SESSION.post(API, headers=headers, json=payload, timeout=45)
                if r.status_code == 429:
                    print("  Lens rate limit — stopping"); return _finish(people)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:  # noqa: BLE001
                print(f"  Lens query {applicant!r} failed: {exc}")
                break
            hits = data.get("data") or []
            for pat in hits:
                parties = ((pat.get("biblio") or {}).get("parties") or {})
                assignees = [a.get("extracted_name", {}).get("value")
                             for a in parties.get("applicants", [])]
                assignee = next((a for a in assignees if a), applicant)
                for inv in parties.get("inventors", []):
                    nm = inv.get("extracted_name", {}).get("value")
                    if not nm or not _looks_like_person(nm):
                        continue
                    cc = (inv.get("residence") or "").upper()[:2]
                    key = strip_accents(_flip(nm)).lower()
                    rec = people.setdefault(key, {
                        "name": _flip(nm), "employer": assignee,
                        "country_code": cc or None,
                        "country": COUNTRY_BY_CODE.get(cc),
                        "via_applicant": applicant, "patent_count": 0,
                    })
                    rec["patent_count"] += 1
                    if cc and not rec["country_code"]:
                        rec["country_code"], rec["country"] = cc, COUNTRY_BY_CODE.get(cc)
            scroll_id = data.get("scroll_id")
            pages += 1
            if not scroll_id or len(hits) < 100:
                break
            time.sleep(1)
        print(f"  Lens[{applicant}]: {len(people)} distinct inventors so far")

    return _finish(people)


def _finish(people: dict) -> list[dict]:
    out = sorted(people.values(), key=lambda p: -p["patent_count"])
    (RAW / "lens_inventors.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Lens: {len(out)} distinct inventors on patents from Balseiro-linked orgs "
          f"({sum(1 for p in out if p['country_code'])} with a residence country)")
    return out


if __name__ == "__main__":
    collect()
