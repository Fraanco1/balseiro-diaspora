"""Collect Balseiro alumni from Wikidata (people with P69 = Instituto Balseiro).

Wikidata is the highest-quality source: it links a person to employers that
themselves carry coordinates, plus occupation, field, image and dates.
Output: data/raw/wikidata_alumni.json  (list of normalised person records)
"""
from __future__ import annotations

import json

from common import RAW, WIKIDATA_QID, cached_get

SPARQL = f"""
SELECT ?person ?personLabel ?personDescription ?article
       ?dob ?dod ?genderLabel ?image
       (GROUP_CONCAT(DISTINCT ?occLabel; separator=" | ") AS ?occs)
       (GROUP_CONCAT(DISTINCT ?fieldLabel; separator=" | ") AS ?fields)
       (GROUP_CONCAT(DISTINCT ?emp; separator=" | ") AS ?employers)
       ?orcid ?scholar
WHERE {{
  ?person wdt:P31 wd:Q5 ; wdt:P69 wd:{WIKIDATA_QID} .
  OPTIONAL {{ ?person wdt:P569 ?dob }}
  OPTIONAL {{ ?person wdt:P570 ?dod }}
  OPTIONAL {{ ?person wdt:P21 ?gender }}
  OPTIONAL {{ ?person wdt:P18 ?image }}
  OPTIONAL {{ ?person wdt:P496 ?orcid }}
  OPTIONAL {{ ?person wdt:P1960 ?scholar }}
  OPTIONAL {{ ?person wdt:P106 ?occ .
             ?occ rdfs:label ?occLabel . FILTER(LANG(?occLabel)="en") }}
  OPTIONAL {{ ?person wdt:P101 ?field .
             ?field rdfs:label ?fieldLabel . FILTER(LANG(?fieldLabel)="en") }}
  OPTIONAL {{ ?person wdt:P108 ?employerItem .
             ?employerItem rdfs:label ?employerItemLabel . FILTER(LANG(?employerItemLabel)="en")
             OPTIONAL {{ ?employerItem wdt:P625 ?employerCoord }}
             OPTIONAL {{ ?employerItem wdt:P17 ?employerCountryItem .
                        ?employerCountryItem rdfs:label ?employerCountryLabel . FILTER(LANG(?employerCountryLabel)="en") }}
             BIND(CONCAT(?employerItemLabel, "@@",
                         COALESCE(STR(?employerCoord), ""), "@@",
                         COALESCE(?employerCountryLabel, "")) AS ?emp) }}
  OPTIONAL {{ ?article schema:about ?person ; schema:isPartOf <https://en.wikipedia.org/> }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,es" }}
}}
GROUP BY ?person ?personLabel ?personDescription ?article ?dob ?dod ?genderLabel ?image ?orcid ?scholar
"""


def _year(iso: str | None):
    if not iso:
        return None
    try:
        return int(iso[:4]) if iso[0] != "-" else -int(iso[1:5])
    except ValueError:
        return None


def _parse_point(text: str):
    # "Point(-74.66 40.33)"
    try:
        lon, lat = text.strip()[6:-1].split()
        return float(lat), float(lon)
    except Exception:
        return None


def collect() -> list[dict]:
    print("Wikidata: querying SPARQL endpoint ...")
    data = cached_get(
        "https://query.wikidata.org/sparql",
        params={"query": SPARQL, "format": "json"},
        throttle_key="wikidata", min_interval=2.0, ttl_days=14,
    )
    rows = data["results"]["bindings"]
    people = []
    for r in rows:
        def g(k):
            return r[k]["value"] if k in r else None

        employers = []
        for chunk in (g("employers") or "").split(" | "):
            if not chunk.strip():
                continue
            label, coord, country = (chunk.split("@@") + ["", ""])[:3]
            latlon = _parse_point(coord) if coord else None
            employers.append({
                "name": label.strip(),
                "lat": latlon[0] if latlon else None,
                "lon": latlon[1] if latlon else None,
                "country": country.strip() or None,
            })

        occs = [o for o in (g("occs") or "").split(" | ") if o]
        fields = [f for f in (g("fields") or "").split(" | ") if f]
        people.append({
            "source": "wikidata",
            "id": g("person").rsplit("/", 1)[-1],
            "name": g("personLabel"),
            "description": g("personDescription"),
            "birth_year": _year(g("dob")),
            "death_year": _year(g("dod")),
            "gender": g("genderLabel"),
            "image": g("image"),
            "occupations": occs,
            "fields": fields,
            "employers": employers,
            "orcid": g("orcid"),
            "scholar_id": g("scholar"),
            "wikipedia": g("article"),
            "wikidata_url": g("person"),
        })

    # de-dupe by QID (GROUP BY should already do this, but be safe)
    uniq = {p["id"]: p for p in people}
    out = sorted(uniq.values(), key=lambda p: p["name"] or "")
    (RAW / "wikidata_alumni.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wikidata: {len(out)} people "
          f"({sum(1 for p in out if p['employers'])} with an employer).")
    return out


if __name__ == "__main__":
    collect()
