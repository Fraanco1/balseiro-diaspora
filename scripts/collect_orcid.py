"""Collect Balseiro alumni from ORCID.

Strategy:
  1. Use the public expanded-search API to find ORCID iDs whose affiliations
     mention Instituto Balseiro (or its aliases).
  2. Fetch each full record and keep the person only if Balseiro appears in
     their *education or qualification* history (i.e. they actually studied
     there -- staff who trained elsewhere are tagged 'affiliate' and dropped).
  3. Extract graduation year, degree, keywords, and the current / most recent
     employer with its city + country for geocoding.

Output: data/raw/orcid_alumni.json
"""
from __future__ import annotations

import json

from common import BALSEIRO_NAME_PATTERNS, RAW, cached_get, strip_accents

SEARCH_TERMS = [
    'affiliation-org-name:"Instituto Balseiro"',
    'affiliation-org-name:"Balseiro Institute"',
    'affiliation-org-name:"Instituto Balseiro"',
]
PUB = "https://pub.orcid.org/v3.0"


def _matches_balseiro(text: str | None) -> bool:
    if not text:
        return False
    t = strip_accents(text).lower()
    return any(p in t for p in BALSEIRO_NAME_PATTERNS)


def _find_ids() -> set[str]:
    ids: set[str] = set()
    for term in SEARCH_TERMS:
        start, page = 0, 200
        while True:
            data = cached_get(
                f"{PUB}/expanded-search/",
                params={"q": term, "start": start, "rows": page},
                throttle_key="orcid", min_interval=0.4, ttl_days=14,
                cache_key=f"orcid-search::{term}::{start}",
            )
            hits = data.get("expanded-result") or []
            for h in hits:
                ids.add(h["orcid-id"])
            if len(hits) < page or start + page >= min(int(data.get("num-found", 0)), 1000):
                break
            start += page
    print(f"ORCID: {len(ids)} candidate iDs from search")
    return ids


def _date_year(d):
    try:
        return int((d or {}).get("year", {}).get("value"))
    except (TypeError, ValueError):
        return None


def _affil(summary):
    v = next(iter(summary.values()))
    org = v.get("organization") or {}
    addr = org.get("address") or {}
    return {
        "role": (v.get("role-title") or "").strip() or None,
        "org": (org.get("name") or "").strip() or None,
        "department": (v.get("department-name") or "").strip() or None,
        "city": addr.get("city"),
        "region": addr.get("region"),
        "country_code": addr.get("country"),
        "start_year": _date_year(v.get("start-date")),
        "end_year": _date_year(v.get("end-date")),
        "ongoing": v.get("end-date") in (None, {}),
    }


def _iter_affils(activities, section):
    for grp in (activities.get(section) or {}).get("affiliation-group", []):
        for s in grp.get("summaries", []):
            yield _affil(s)


def collect() -> list[dict]:
    ids = _find_ids()
    people: list[dict] = []
    kept = affiliate_only = 0
    for i, oid in enumerate(sorted(ids), 1):
        if i % 50 == 0:
            print(f"  ORCID records {i}/{len(ids)}")
        try:
            rec = cached_get(f"{PUB}/{oid}/record", throttle_key="orcid",
                             min_interval=0.34, ttl_days=45,
                             cache_key=f"orcid-record::{oid}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {oid}: {exc}")
            continue

        person = rec.get("person") or {}
        nm = person.get("name") or {}
        if (nm.get("visibility") == "limited") or not nm:
            continue
        given = ((nm.get("given-names") or {}) or {}).get("value") or ""
        family = ((nm.get("family-name") or {}) or {}).get("value") or ""
        credit = ((nm.get("credit-name") or {}) or {}).get("value") or ""
        name = credit or f"{given} {family}".strip()
        if not name:
            continue

        activities = rec.get("activities-summary") or {}
        educations = list(_iter_affils(activities, "educations"))
        qualifications = list(_iter_affils(activities, "qualifications"))
        employments = list(_iter_affils(activities, "employments"))

        balseiro_edu = [e for e in educations + qualifications if _matches_balseiro(e["org"])]
        if not balseiro_edu:
            # only shows up as employer/other affiliation -> not an alumnus
            if any(_matches_balseiro(e["org"]) for e in employments):
                affiliate_only += 1
            continue

        grad_year = max((e["end_year"] for e in balseiro_edu if e["end_year"]), default=None)
        degrees = sorted({e["role"] for e in balseiro_edu if e["role"]})

        # current employer = ongoing with latest start, else most recent by end year
        non_balseiro_emp = [e for e in employments if not _matches_balseiro(e["org"])]
        current = None
        ongoing = [e for e in non_balseiro_emp if e["ongoing"]]
        if ongoing:
            current = max(ongoing, key=lambda e: e["start_year"] or 0)
        elif non_balseiro_emp:
            current = max(non_balseiro_emp, key=lambda e: (e["end_year"] or 0, e["start_year"] or 0))

        keywords = [k.get("content", "").strip()
                    for k in ((person.get("keywords") or {}).get("keyword") or [])]
        keywords = [k for w in keywords for k in (w.split(",") if "," in w else [w])]
        keywords = sorted({k.strip() for k in keywords if k.strip()})

        urls = [u.get("url", {}).get("value")
                for u in ((person.get("researcher-urls") or {}).get("researcher-url") or [])]

        people.append({
            "source": "orcid",
            "id": oid,
            "orcid": oid,
            "name": name,
            "grad_year": grad_year,
            "degrees": degrees,
            "keywords": keywords,
            "urls": [u for u in urls if u],
            "biography": ((person.get("biography") or {}) or {}).get("content"),
            "current_employer": current,
            "all_employers": non_balseiro_emp,
        })
        kept += 1

    out = sorted(people, key=lambda p: p["name"].lower())
    (RAW / "orcid_alumni.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"ORCID: kept {kept} alumni (studied at Balseiro); "
          f"{affiliate_only} affiliates-only skipped; "
          f"{sum(1 for p in out if p['current_employer'])} have a current employer.")
    return out


if __name__ == "__main__":
    collect()
