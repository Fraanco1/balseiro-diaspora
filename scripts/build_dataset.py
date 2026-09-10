"""Merge every source into a single site/data/alumni.json for the website.

Steps
-----
1. Load the raw per-source files (Wikidata, ORCID, Wikipedia, OpenAlex, and
   the optional RICABIB thesis harvest) + hand-editable CSVs
   (data/manual_alumni.csv, data/review_candidates.csv) and data/blocklist.txt.
2. Merge records that refer to the same person (by ORCID iD, then by a
   normalised name key).
3. OpenAlex: enrich matched people with publication stats / research concepts,
   add high-confidence ORCID-less authors, and (re)write the review queue.
4. Resolve each person's *current* location (institution -> lat/lon) from
   coordinates already in Wikidata / OpenAlex, else geocoding "<org>, <city>,
   <country>" via Nominatim (cached in data/geocode_cache.json).
5. Classify research field + employer sector; tag confidence.
6. Write site/data/alumni.json (list + meta) — the only file the site loads.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re

from common import (DATA, SITE_DATA, ROOT, geocode_many, name_key, strip_accents,
                    initial_key, is_initials_form)
import collect_openalex

RAW_FILES = {
    "wikidata": DATA / "raw" / "wikidata_alumni.json",
    "orcid": DATA / "raw" / "orcid_alumni.json",
    "wikipedia": DATA / "raw" / "wikipedia_alumni.json",
    "openalex": DATA / "raw" / "openalex_authors.json",
    "ricabib": DATA / "raw" / "ricabib_theses.json",
}
MANUAL_CSV = DATA / "manual_alumni.csv"
REVIEW_CSV = DATA / "review_candidates.csv"
BLOCKLIST = DATA / "blocklist.txt"

# OpenAlex review_score thresholds (see collect_openalex._score):
OA_AUTO_KEEP = 5.5      # >= this: added straight to the map, tagged 'openalex'
OA_REVIEW_MIN = 3.5     # [MIN, AUTO_KEEP): written to review_candidates.csv

COUNTRY_BY_CODE = {
    "AR": "Argentina", "US": "United States", "BR": "Brazil", "DE": "Germany",
    "ES": "Spain", "FR": "France", "GB": "United Kingdom", "UK": "United Kingdom",
    "IT": "Italy", "CH": "Switzerland", "NL": "Netherlands", "CA": "Canada",
    "MX": "Mexico", "CL": "Chile", "SE": "Sweden", "BE": "Belgium", "AT": "Austria",
    "AU": "Australia", "JP": "Japan", "CN": "China", "PT": "Portugal", "DK": "Denmark",
    "NO": "Norway", "FI": "Finland", "IL": "Israel", "IN": "India", "PL": "Poland",
    "CZ": "Czechia", "CO": "Colombia", "UY": "Uruguay", "PE": "Peru", "KR": "South Korea",
    "IE": "Ireland", "NZ": "New Zealand", "SG": "Singapore", "ZA": "South Africa",
}

DISCIPLINE_RULES = [
    ("Particle & high-energy physics", r"particle physic|high[- ]energy|quantum field|standard model|collider|hadron|neutrino|lhc\b|atlas experiment"),
    ("String theory & gravitation", r"string theory|superstring|supergravit|gravitation|holograph|ads/cft|black hole|cosmolog|general relativ|quantum gravity"),
    ("Quantum information & computing", r"quantum info|quantum comput|qubit|quantum optic|entanglement|quantum technolog|quantum simulation"),
    ("Condensed matter & materials", r"condensed matter|solid[- ]state|material science|materials science|superconduct|magnetism|magnetic material|\balloy|aleacion|nanostructur|nanoscien|nanotechnolog|nanopart|spintron|semiconductor|thin film|\bcrystal|metallurg|corrosion|graphene|hydrogen storage|shape memory|multiferroic|multilayer|anisotropy|sintering"),
    ("Astrophysics & astronomy", r"astrophys|astronom|cosmic ray|galax|stellar|exoplanet|planetary scien|solar physic"),
    ("Nuclear engineering & energy", r"nuclear|reactor|fission|neutron|monte carlo (method|simulation|code)|radioprotection|radiation protection|fuel (cycle|element)|radioisotop|nucleoelectr|criticality|thermal[- ]hydraulic|hydrogen (storage|embrittlement|absorption)"),
    ("Plasma & fusion physics", r"plasma|tokamak|fusion|magnetohydro"),
    ("Atmospheric, earth & environment", r"atmospher|climate|meteorolog|geophys|environment|oceanograph|hydrolog|glaciolog|earth scien|renewable energ|solar energ|wind energ"),
    ("Biophysics, medical & health physics", r"biophys|medical physic|health physic|radiotherap|dosimetr|biomedic|neuroscien|molecular biolog|medicine|clinical|hospital|health"),
    ("Photonics & optics", r"photonic|optic|laser|plasmonic|spectroscop|holograph"),
    ("Computer science, data & AI", r"machine learning|artificial intelligence|deep learning|neural network|computer scien|data scien|data analy|software|algorithm|comput\w* vision|blockchain|cryptograph|informatic"),
    ("Mechanical & aerospace engineering", r"mechanical eng|aerospace|aeronaut|fluid dynam|fluid mechanic|thermodynam|combustion|turbomachin|structural eng|manufacturing"),
    ("Electronics, control & telecom", r"electronic|telecommunicat|signal processing|\bradar\b|\bsonar\b|antenna|microwave|\bfpga\b|embedded system|control system|\bsensors?\b|instrumentation|\bcircuit"),
    ("Mathematics & statistics", r"mathematic|statistic|probability|topolog|geometry|number theory|differential equation|dynamical system"),
    ("Complex systems & statistical physics", r"complex system|statistical (physic|mechanic)|network scien|econophys|nonlinear dynam|agent[- ]based|sociophys"),
    ("Economics, finance & policy", r"econophysic|quantitative finance|financial market|quantitative analyst|science polic|actuaria"),
]

# Coarse fallback when nothing specific matches, based on the Balseiro degree.
PROGRAM_TO_DISCIPLINE = {
    "Physics": "Physics (general)",
    "Nuclear engineering": "Nuclear engineering & energy",
    "Mechanical engineering": "Mechanical & aerospace engineering",
    "Telecommunications engineering": "Electronics, control & telecom",
}

SECTOR_RULES = [
    ("Industry / company", r"\b(inc|ltd|llc|gmbh|ltda|corp|co\.|pvt|ab|sl|srl|bv)\b|s\.?a\.?s?\b|technolog(y|ies|ia|ía)|\bsolutions\b|\bsystems\b|\bsoftware\b|semiconductor|consult|satellogic|\binvap\b|\bgoogle\b|microsoft|amazon|\bintel\b|\bibm\b|nvidia|bosch|siemens|\bbank\b|\bcapital\b|quantum computing|quantum tech|recursion|traceable|hutek|startup|accenture|grumman|\bypf\b|\bmerck\b|quandela|qilimanjaro|studsvik|ikerlan|seamplex|innomerics|molecular gate|4feedstock|candu owners|itaipu|nucleoel[eé]ctrica|\btecna\b"),
    ("Government & national lab", r"national laborator|nacional de energ|atomic energy|\bcnea\b|comisi[oó]n nacional|nuclear regulatory|\bcern\b|\bnasa\b|\bconae\b|ministr|ministerio|\bagency\b|agencia (nuclear|espacial|nacional)|oak ridge|los alamos|brookhaven|fermilab|fermi national|argonne|\bslac\b|jefferson lab|\bnist\b|\binta\b|servicio geol|physikalisch-technische bundesanstalt|estaci[oó]n experimental"),
    ("Research institute / council", r"institut|instituto|istituto|centro at[oó]mico|atomic cent(re|er)|centro cient|centro de investigaci|laboratoir|\blaboratory\b|\bcnrs\b|\bcsic\b|\bconicet\b|\bifiba\b|\binfina\b|consejo (nacional|superior) de investigaci|national (council for scientific|scientific and technical)|research council|research (centre|center)|synchrotron|supercomputing (cent(er|re)|center)|physics cent(er|re)|max planck|helmholtz|leibniz|fraunhofer|forschungszentrum|\briken\b|weizmann|perimeter institute|kavli|flatiron|\bictp\b|\bgssi\b|\bicrea\b|\bcinvestav\b|cea saclay|\bcea\b|\bimdea\b|academ(y|ia) of scien|consiglio nazionale|foundation|fundaci[oó]n"),
    ("University / academia", r"universi|universidad|universit[aeà]|\buniv\b|college|coll[eè]ge|\bescuela\b|\bfacultad\b|\bfiuba\b|faculty of|school of|polytechnic|polit[eé]cnic|\becole\b|eth z[uü]rich|\bepfl\b|\bmit\b|caltech|leuven|\bunam\b|\buba\b|\bunc\b|\bunlp\b|\buns\b|\butn\b|unizar|\bupm\b|\bkit\b"),
    ("Hospital / clinic", r"klinikum|hospital|\bclinic\b|cl[ií]nica"),
    ("School / secondary education", r"\bcolegio|colegios|\be\.?e\.?t\.?\b|escuela t[eé]cnica|escuela de ense|secondary school|high school|\bliceo\b"),
]

DEGREE_PROGRAM_RULES = [
    ("Physics", r"physics|f[ií]sic|licenciatura en f"),
    ("Nuclear engineering", r"nuclear"),
    ("Mechanical engineering", r"mechanic|mec[aá]nic"),
    ("Telecommunications engineering", r"telecom"),
]

# Level of study at Balseiro. Checked in order; a person can match several
# (e.g. did the Licenciatura *and* the Doctorado there).
DEGREE_LEVEL_RULES = [
    ("Doctorate (PhD)", r"\bph\.?\s?d|\bdoctor|\bdr\.?\b|doctorad|doctoral"),
    ("Master's", r"\bmaster|mag[ií]ster|maestr[ií]a|\bm\.?\s?sc|\bmsc\b|magister"),
    ("Specialization / diploma", r"especialist|especializaci[oó]n|\bspecialist|diploma de espec|carrera de especial"),
    ("Engineering degree", r"\bengineer\b|ingenier[oí]|engineering degree|proyecto integrador|nuclear engineer|mechanical engineer"),
    ("Physics degree (Licenciatura)", r"licenciad|licenciatura|bachelor|grado en f[ií]s|physics degree|licentiate"),
]


def _classify(text: str, rules, default=None):
    t = strip_accents(text or "").lower()
    for label, pattern in rules:
        if re.search(pattern, t):
            return label
    return default


def _classify_all(text: str, rules) -> list[str]:
    t = strip_accents(text or "").lower()
    return [label for label, pattern in rules if re.search(pattern, t)]


# --------------------------------------------------------------------------- #
def _blank_person():
    return {
        "name": None, "aka": set(), "orcid": None, "scholar_id": None,
        "wikidata_url": None, "wikipedia": None, "image": None,
        "description": None, "biography": None,
        "birth_year": None, "death_year": None,
        "grad_year": None, "degrees": set(), "degree_program": None,
        "keywords": set(), "occupations": set(), "fields": set(),
        "employer_name": None, "employer_city": None, "employer_country": None,
        "employer_country_code": None, "lat": None, "lon": None,
        "role": None, "sources": set(), "urls": set(),
        "works_count": None, "h_index": None, "concepts": set(),
        "thesis_title": None, "thesis_year": None,
        "wikidata_alumnus": None,   # None unknown / True P69 / False staff-only
        "_wd_employers": [], "_orcid_current": None, "_openalex": None,
    }


def _merge_wikidata(idx, by_orcid, by_name):
    for p in json.loads(RAW_FILES["wikidata"].read_text(encoding="utf-8")):
        key = ("orcid", p["orcid"]) if p.get("orcid") else ("name", name_key(p["name"]))
        rec = idx.setdefault(key, _blank_person())
        rec["name"] = rec["name"] or p["name"]
        rec["sources"].add("wikidata")
        rec["orcid"] = rec["orcid"] or p.get("orcid")
        rec["scholar_id"] = rec["scholar_id"] or p.get("scholar_id")
        rec["wikidata_url"] = p.get("wikidata_url")
        rec["wikipedia"] = rec["wikipedia"] or p.get("wikipedia")
        rec["image"] = rec["image"] or p.get("image")
        rec["description"] = rec["description"] or p.get("description")
        rec["birth_year"] = rec["birth_year"] or p.get("birth_year")
        rec["death_year"] = rec["death_year"] or p.get("death_year")
        rec["occupations"].update(p.get("occupations") or [])
        rec["fields"].update(p.get("fields") or [])
        rec["degrees"].update(p.get("degrees") or [])
        rec["_wd_employers"] = p.get("employers") or []
        if p.get("is_alumnus"):
            rec["wikidata_alumnus"] = True
        elif rec["wikidata_alumnus"] is None:
            rec["wikidata_alumnus"] = False
        if p.get("orcid"):
            by_orcid[p["orcid"]] = key
        by_name.setdefault(name_key(p["name"]), key)


def _merge_orcid(idx, by_orcid, by_name):
    records = json.loads(RAW_FILES["orcid"].read_text(encoding="utf-8"))
    thesis_orcid = DATA / "raw" / "thesis_orcid.json"
    if thesis_orcid.exists():
        records += json.loads(thesis_orcid.read_text(encoding="utf-8"))
    seen_oid = set()
    for p in records:
        if p["orcid"] in seen_oid:
            continue
        seen_oid.add(p["orcid"])
        nk = name_key(p["name"])
        key = by_orcid.get(p["orcid"]) or by_name.get(nk) or ("orcid", p["orcid"])
        rec = idx.setdefault(key, _blank_person())
        rec["name"] = rec["name"] or p["name"]
        if p["name"] and rec["name"] and p["name"] != rec["name"]:
            rec["aka"].add(p["name"])
        rec["sources"].add("orcid")
        rec["orcid"] = rec["orcid"] or p.get("orcid")
        rec["grad_year"] = rec["grad_year"] or p.get("grad_year")
        rec["degrees"].update(p.get("degrees") or [])
        rec["keywords"].update(p.get("keywords") or [])
        rec["biography"] = rec["biography"] or p.get("biography")
        rec["urls"].update(p.get("urls") or [])
        rec["_orcid_current"] = p.get("current_employer")
        by_orcid.setdefault(p["orcid"], key)
        by_name.setdefault(nk, key)


def _merge_wikipedia(idx, by_orcid, by_name):
    for p in json.loads(RAW_FILES["wikipedia"].read_text(encoding="utf-8")):
        nk = name_key(p["name"])
        key = by_name.get(nk)
        if key is None and p.get("qid"):
            for k, v in idx.items():
                if (v.get("wikidata_url") or "").endswith("/" + p["qid"]):
                    key = k
                    break
        key = key or ("name", nk)
        rec = idx.setdefault(key, _blank_person())
        rec["name"] = rec["name"] or p["name"]
        rec["sources"].add("wikipedia")
        rec["wikipedia"] = rec["wikipedia"] or p.get("wikipedia")
        rec["image"] = rec["image"] or p.get("image")
        rec["description"] = rec["description"] or p.get("description")
        by_name.setdefault(nk, key)


def _merge_csv(idx, by_name, path, source_tag, kept_only=False):
    """Merge a hand-editable CSV of people (manual_alumni.csv or the kept rows
    of review_candidates.csv). Only `name` is required."""
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row = {k: (v or "").strip() for k, v in row.items() if k}
            if not row.get("name") or row["name"].lstrip().startswith("#"):
                continue
            if kept_only and row.get("keep", "").lower() not in ("y", "yes", "1", "x", "true"):
                continue
            nk = name_key(row["name"])
            key = by_name.get(nk) or ("name", nk)
            rec = idx.setdefault(key, _blank_person())
            rec["name"] = rec["name"] or row["name"]
            rec["sources"].add(source_tag)
            for field in ("grad_year", "role", "degree_program", "description"):
                if row.get(field):
                    rec[field] = row[field]
            if row.get("field"):
                rec["fields"].add(row["field"])
            if row.get("concepts"):
                rec["concepts"].update(c.strip() for c in row["concepts"].split(";") if c.strip())
            for u in re.split(r"[;\s]+", row.get("links", "") + " " + row.get("openalex_url", "")):
                if u:
                    rec["urls"].add(u)
            if row.get("employer") or row.get("current_institution"):
                rec["employer_name"] = row.get("employer") or row.get("current_institution")
            if row.get("city"):
                rec["employer_city"] = row["city"]
            if row.get("country"):
                rec["employer_country"] = row["country"]
            try:
                if row.get("lat") and row.get("lon"):
                    rec["lat"], rec["lon"] = float(row["lat"]), float(row["lon"])
            except ValueError:
                pass
            by_name.setdefault(nk, key)
            n += 1
    return n


def _load_openalex():
    out = []
    for f in (RAW_FILES["openalex"], DATA / "raw" / "thesis_reconciled.json"):
        if f.exists():
            out += json.loads(f.read_text(encoding="utf-8"))
    # de-dupe by OpenAlex id, preferring the richer Balseiro-pool record
    by_id = {}
    for a in out:
        by_id.setdefault(a["openalex_id"], a)
    return list(by_id.values())


def _oa_location(inst):
    """(lat, lon, city, country, country_code) for an OpenAlex institution dict."""
    if not inst:
        return None
    geo = collect_openalex.institution_geo(inst.get("openalex_id"))
    if geo:
        return geo
    cc = (inst.get("country_code") or "").upper()
    return {"lat": None, "lon": None, "city": None,
            "country": COUNTRY_BY_CODE.get(cc), "country_code": cc or None}


def _build_ikey_index(idx):
    """initial_key -> idx key, or None where two different people collide."""
    by_ikey = {}
    for key, rec in idx.items():
        ik = initial_key(rec["name"] or "")
        if not ik or ik.endswith("|"):
            continue
        by_ikey[ik] = key if ik not in by_ikey else (
            by_ikey[ik] if by_ikey[ik] == key else None)
    return by_ikey


def _enrich_openalex(idx, by_orcid, by_name, blocked):
    """Attach OpenAlex stats to people we already have, and add the
    high-confidence ORCID-less authors straight to the map."""
    authors = _load_openalex()
    by_ikey = _build_ikey_index(idx)
    added = enriched = via_initials = 0
    for a in authors:
        nk = name_key(a["name"])
        if nk in blocked:
            continue
        key = (by_orcid.get(a["orcid"]) if a.get("orcid") else None) or by_name.get(nk)

        # "A. Baruj" (OpenAlex) vs "Alberto Baruj" (thesis roster): match on the
        # looser initials key, but only when it points to exactly one person.
        if key is None and is_initials_form(a["name"]):
            ik_key = by_ikey.get(initial_key(a["name"]))
            if ik_key is not None:
                key = ik_key
                via_initials += 1

        if key is None:
            if (a.get("review_score") or 0) < OA_AUTO_KEEP:
                continue  # handled by the review queue instead
            key = ("oa", a["openalex_id"])
            idx[key] = _blank_person()
            idx[key]["name"] = a["name"]
            idx[key]["sources"].add("openalex")
            by_name.setdefault(nk, key)
            loc = _oa_location(a.get("current_institution"))
            if loc:
                ci = a["current_institution"]
                idx[key]["employer_name"] = ci.get("name")
                idx[key]["lat"], idx[key]["lon"] = loc["lat"], loc["lon"]
                idx[key]["employer_city"] = loc.get("city")
                idx[key]["employer_country"] = loc.get("country")
                idx[key]["employer_country_code"] = loc.get("country_code")
            added += 1

        rec = idx[key]
        rec["_openalex"] = a
        rec["works_count"] = a.get("works_count") or rec["works_count"]
        rec["h_index"] = a.get("h_index") or rec["h_index"]
        rec["concepts"].update(a.get("concepts") or [])
        if a.get("orcid") and not rec["orcid"]:
            rec["orcid"] = a["orcid"]
        if not rec["grad_year"] and a.get("balseiro_years"):
            rec["grad_year"] = min(a["balseiro_years"])
        enriched += 1
    print(f"OpenAlex merge: enriched {enriched} people "
          f"({via_initials} matched to a roster name by initials), "
          f"added {added} new (score >= {OA_AUTO_KEEP})")


def _write_review_queue(idx, by_orcid, by_name, blocked):
    """Regenerate review_candidates.csv for the mid-confidence ORCID-less
    OpenAlex authors, preserving any `keep` marks already set."""
    prior = {}
    if REVIEW_CSV.exists():
        with REVIEW_CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("openalex_id"):
                    prior[row["openalex_id"]] = row.get("keep", "")

    rows = []
    for a in _load_openalex():
        s = a.get("review_score") or 0
        if not (OA_REVIEW_MIN <= s < OA_AUTO_KEEP):
            continue
        nk = name_key(a["name"])
        if nk in blocked:
            continue
        if (a.get("orcid") and a["orcid"] in by_orcid) or nk in by_name:
            continue  # already in the dataset from another source
        ci = a.get("current_institution") or {}
        rows.append({
            "keep": prior.get(a["openalex_id"], ""),
            "name": a["name"],
            "score": s,
            "grad_year": min(a["balseiro_years"]) if a.get("balseiro_years") else "",
            "current_institution": ci.get("name") or "",
            "country": COUNTRY_BY_CODE.get((ci.get("country_code") or "").upper(),
                                           ci.get("country_code") or ""),
            "city": "", "employer": "", "lat": "", "lon": "",
            "degree_program": "", "field": "",
            "concepts": "; ".join(a.get("concepts") or []),
            "works": a.get("works_count") or "",
            "openalex_url": f"https://openalex.org/{a['openalex_id']}",
            "openalex_id": a["openalex_id"],
        })
    rows.sort(key=lambda r: -r["score"])

    cols = ["keep", "name", "score", "grad_year", "current_institution", "country",
            "city", "employer", "lat", "lon", "degree_program", "field",
            "concepts", "works", "openalex_url", "openalex_id"]
    with REVIEW_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerow({"keep": "# set keep=y to add a row to the map; "
                            "fill city/country or lat,lon if the institution is wrong or missing",
                    "name": "", "score": ""})
        w.writerows(rows)
    kept = sum(1 for r in rows if r["keep"].lower() in ("y", "yes", "1", "x", "true"))
    print(f"review queue: {len(rows)} candidates in {REVIEW_CSV.name} "
          f"({kept} marked keep)")


def _merge_ricabib(idx, by_name):
    """Optional: IB thesis repository (author + year + title) — authoritative
    alumni names. Run scripts/collect_ricabib.py from Argentina to populate it."""
    if not RAW_FILES["ricabib"].exists():
        return 0
    n = 0
    for t in json.loads(RAW_FILES["ricabib"].read_text(encoding="utf-8")):
        if not t.get("author"):
            continue
        nk = name_key(t["author"])
        key = by_name.get(nk) or ("name", nk)
        rec = idx.setdefault(key, _blank_person())
        rec["name"] = rec["name"] or t["author"]
        rec["sources"].add("ricabib")
        rec["thesis_title"] = rec["thesis_title"] or t.get("title")
        rec["thesis_year"] = rec["thesis_year"] or t.get("year")
        rec["keywords"].update(s for s in (t.get("subjects") or []) if s.isascii())
        if not rec["grad_year"] and t.get("year"):
            rec["grad_year"] = t["year"]
        if t.get("degree_program") and not rec["degree_program"]:
            rec["degree_program"] = t["degree_program"]
        by_name.setdefault(nk, key)
        n += 1
    return n


def _load_blocklist():
    if not BLOCKLIST.exists():
        return set()
    out = set()
    for line in BLOCKLIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(name_key(line))
    return out


# --------------------------------------------------------------------------- #
def _chain(*queries):
    """Ordered, de-duplicated list of non-empty geocode queries to try."""
    seen, out = set(), []
    for q in queries:
        q = (q or "").strip(" ,")
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def _resolve_location(rec):
    """Fill employer_name / city / country and set rec['_geo_chain'].

    The chain lists progressively looser geocode queries; the first that
    resolves wins (institution -> city -> country). City-level is good enough
    for a world map and rescues long, messy institution names.
    """
    oc = rec["_orcid_current"]
    wd = [e for e in rec["_wd_employers"] if e.get("name")]
    wd_with_coord = [e for e in wd if e.get("lat") is not None]
    rec["_geo_chain"] = []

    # 1. explicit manual coords already set
    if rec["lat"] is not None and rec["lon"] is not None:
        rec["employer_name"] = rec["employer_name"] or (oc or {}).get("org") or (wd[0]["name"] if wd else None)
        return

    # 1b. manual CSV row with an employer/city/country but no coords -> geocode it.
    #     (checked before Wikidata/ORCID so hand-added people are honoured.)
    if "manual" in rec["sources"] and not oc and not wd and (
            rec["employer_name"] or rec["employer_city"] or rec["employer_country"]):
        org, city, country = rec["employer_name"], rec["employer_city"], rec["employer_country"]
        rec["_geo_chain"] = _chain(
            ", ".join(b for b in [org, city, country] if b),
            ", ".join(b for b in [org, country] if b),
            ", ".join(b for b in [city, country] if b),
            country,
        )
        return

    # 2. Wikidata employer that carries coordinates (highest quality)
    if wd_with_coord and not (oc and oc.get("ongoing")):
        e = wd_with_coord[0]
        rec.update(employer_name=e["name"], employer_country=e.get("country"),
                   lat=e["lat"], lon=e["lon"])
        rec["role"] = rec["role"] or _nice_role(rec)
        return

    # 3. ORCID current employer
    if oc and oc.get("org"):
        cc = (oc.get("country_code") or "").upper()
        country = COUNTRY_BY_CODE.get(cc, cc or None)
        rec["employer_name"] = oc["org"]
        rec["employer_city"] = oc.get("city")
        rec["employer_country_code"] = cc or None
        rec["employer_country"] = COUNTRY_BY_CODE.get(cc, rec["employer_country"])
        rec["role"] = rec["role"] or oc.get("role")
        rec["_geo_chain"] = _chain(
            ", ".join(b for b in [oc["org"], oc.get("city"), country] if b),
            ", ".join(b for b in [oc["org"], country] if b),
            ", ".join(b for b in [oc.get("city"), oc.get("region"), country] if b),
            ", ".join(b for b in [oc.get("city"), country] if b),
            country,
        )
        return

    # 4. Wikidata employer without coordinates
    if wd:
        e = wd[0]
        rec["employer_name"] = e["name"]
        rec["employer_country"] = e.get("country")
        rec["_geo_chain"] = _chain(
            ", ".join(b for b in [e["name"], e.get("country")] if b),
            e["name"],
            e.get("country"),
        )
        return

    # 5. OpenAlex current institution — try its own coordinates first, then geocode
    oa = rec.get("_openalex") or {}
    ci = oa.get("current_institution") or {}
    if ci.get("name"):
        cc = (ci.get("country_code") or "").upper()
        country = COUNTRY_BY_CODE.get(cc, cc or None)
        rec["employer_name"] = rec["employer_name"] or ci["name"]
        rec["employer_country"] = rec["employer_country"] or country
        geo = collect_openalex.institution_geo(ci.get("openalex_id"))
        if geo:
            rec["lat"], rec["lon"] = geo["lat"], geo["lon"]
            rec["employer_city"] = rec["employer_city"] or geo.get("city")
            rec["employer_country"] = geo.get("country") or rec["employer_country"]
            rec["employer_country_code"] = geo.get("country_code")
            return
        rec["_geo_chain"] = _chain(
            ", ".join(b for b in [ci["name"], country] if b),
            ci["name"], country,
        )
        return


def _nice_role(rec):
    occ = sorted(rec["occupations"])  # sorted -> deterministic across builds
    for pref in ("professor", "physicist", "researcher", "university teacher", "engineer"):
        for o in occ:
            if pref in o.lower():
                return o.capitalize()
    return occ[0] if occ else None


# --------------------------------------------------------------------------- #
def build():
    idx: dict = {}
    by_orcid: dict = {}
    by_name: dict = {}

    blocked = _load_blocklist()

    _merge_wikidata(idx, by_orcid, by_name)
    _merge_orcid(idx, by_orcid, by_name)
    _merge_wikipedia(idx, by_orcid, by_name)
    n_ricabib = _merge_ricabib(idx, by_name)
    n_manual = _merge_csv(idx, by_name, MANUAL_CSV, "manual")

    # OpenAlex: enrich existing people + add high-confidence ORCID-less authors,
    # then (re)write the review queue and fold back any rows already marked keep.
    _enrich_openalex(idx, by_orcid, by_name, blocked)
    _write_review_queue(idx, by_orcid, by_name, blocked)
    n_review = _merge_csv(idx, by_name, REVIEW_CSV, "reviewed", kept_only=True)

    # honour the blocklist (name keys to always drop)
    if blocked:
        before = len(idx)
        for k in [k for k, v in idx.items() if name_key(v["name"] or "") in blocked]:
            del idx[k]
        print(f"blocklist: removed {before - len(idx)}")

    print(f"merged: {len(idx)} distinct people "
          f"(+{n_ricabib} ricabib, +{n_manual} manual, +{n_review} reviewed)")

    # ---- resolve locations (batch-geocode, first hit in each chain wins) -- #
    for rec in idx.values():
        _resolve_location(rec)
    all_queries = [q for rec in idx.values() for q in rec.get("_geo_chain", [])]
    print(f"geocoding {len(set(all_queries))} distinct places "
          f"(fallback chains, city-level allowed) ...")
    resolved = geocode_many(all_queries)
    located_by_chain = 0
    for rec in idx.values():
        rec.setdefault("loc_precision", "institution" if rec["lat"] is not None else None)
        if rec["lat"] is not None:
            continue
        for i, q in enumerate(rec.get("_geo_chain", [])):
            hit = resolved.get(q)
            if hit and hit.get("lat") is not None:
                lat, lon = hit["lat"], hit["lon"]
                # first query = the institution itself; later = city/country only,
                # so nudge those apart with a deterministic sub-degree jitter.
                if i > 0:
                    h = int(hashlib.sha1((rec["name"] or q).encode()).hexdigest(), 16)
                    span = 0.06 if i < len(rec["_geo_chain"]) - 1 else 0.9
                    lat += ((h & 0xFFFF) / 0xFFFF - 0.5) * span
                    lon += (((h >> 16) & 0xFFFF) / 0xFFFF - 0.5) * span
                    rec["loc_precision"] = "city" if i < len(rec["_geo_chain"]) - 1 else "country"
                else:
                    rec["loc_precision"] = "institution"
                rec["lat"], rec["lon"] = lat, lon
                rec["employer_country"] = rec["employer_country"] or hit.get("country")
                rec["employer_country_code"] = rec["employer_country_code"] or hit.get("country_code")
                located_by_chain += 1
                break
    print(f"  located {located_by_chain} more via geocoding")

    # ---- finalise records --------------------------------------------------#
    out = []
    for rec in idx.values():
        degree_blob = " ".join(rec["degrees"]) + " " + (rec["description"] or "") \
            + " " + (rec["thesis_title"] or "")
        program = rec["degree_program"] or _classify(degree_blob, DEGREE_PROGRAM_RULES)
        levels = _classify_all(degree_blob, DEGREE_LEVEL_RULES)

        # Classify the research field, most trustworthy signal first:
        # human-written text -> degree -> (filtered) OpenAlex concepts ->
        # employer name -> coarse bucket from the Balseiro degree.
        human_blob = " ".join([
            " ".join(rec["fields"]), " ".join(rec["keywords"]),
            " ".join(rec["occupations"]), rec["description"] or "",
            rec["biography"] or "", rec["thesis_title"] or "",
        ])
        discipline = (
            _classify(human_blob, DISCIPLINE_RULES, default=None)
            or _classify(" ".join(rec["degrees"]), DISCIPLINE_RULES, default=None)
            or _classify(" ".join(sorted(rec["concepts"])), DISCIPLINE_RULES, default=None)
            or _classify(rec["employer_name"] or "", DISCIPLINE_RULES, default=None)
            or PROGRAM_TO_DISCIPLINE.get(program, "Not specified")
        )

        sector = _classify(rec["employer_name"] or "", SECTOR_RULES, default=None)

        country = rec["employer_country"]
        if not country and rec["employer_country_code"]:
            country = COUNTRY_BY_CODE.get(rec["employer_country_code"])

        gy = rec["grad_year"]
        try:
            gy = int(gy) if gy else None
        except (TypeError, ValueError):
            gy = None

        out.append({
            "name": rec["name"],
            "aka": sorted(rec["aka"]) or None,
            "description": rec["description"],
            "role": rec["role"] or _nice_role(rec),
            "employer": rec["employer_name"],
            "city": rec["employer_city"],
            "country": country,
            "lat": round(rec["lat"], 5) if rec["lat"] is not None else None,
            "lon": round(rec["lon"], 5) if rec["lon"] is not None else None,
            "loc_precision": rec.get("loc_precision"),
            "discipline": discipline,
            "sector": sector,
            "program": program,
            "levels": levels or None,
            "grad_year": gy,
            "grad_decade": (gy // 10 * 10) if gy else None,
            "birth_year": rec["birth_year"],
            "deceased": bool(rec["death_year"]),
            "keywords": sorted(rec["keywords"])[:12] or None,
            "fields": sorted(rec["fields"]) or None,
            "concepts": sorted(rec["concepts"])[:6] or None,
            "works_count": rec["works_count"],
            "h_index": rec["h_index"],
            "thesis": ({"title": rec["thesis_title"], "year": rec["thesis_year"]}
                       if rec["thesis_title"] else None),
            "confidence": ("confirmed" if rec["wikidata_alumnus"]
                           or {"orcid", "wikipedia", "manual", "ricabib", "reviewed"} & rec["sources"]
                           else "inferred"),
            "orcid": rec["orcid"],
            "scholar_id": rec["scholar_id"],
            "wikipedia": rec["wikipedia"],
            "wikidata": rec["wikidata_url"],
            "image": rec["image"],
            "urls": sorted(rec["urls"]) or None,
            "sources": sorted(rec["sources"]),
            "located": rec["lat"] is not None,
        })

    out.sort(key=lambda p: (not p["located"], p["name"].lower()))
    located = [p for p in out if p["located"]]
    countries = sorted({p["country"] for p in located if p["country"]})

    payload = {
        "meta": {
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "institution": "Instituto Balseiro (Bariloche, Argentina)",
            "total": len(out),
            "located": len(located),
            "countries": len(countries),
            "confirmed": sum(1 for p in out if p["confidence"] == "confirmed"),
            "sources": {
                s: sum(1 for p in out if s in p["sources"])
                for s in ("wikidata", "orcid", "openalex", "reviewed",
                          "wikipedia", "ricabib", "manual")
            },
            "disclaimer": (
                "Compiled automatically from public data (Wikidata, ORCID, "
                "OpenAlex, Wikipedia). Coverage is partial and skewed toward "
                "people with an academic/research web presence. 'Inferred' "
                "entries come from OpenAlex affiliation data and are less "
                "certain. Locations are the current or most recent employer on "
                "record and may be out of date."
            ),
        },
        "alumni": out,
    }
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "alumni.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "alumni.pretty.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote site/data/alumni.json  —  {len(out)} people, "
          f"{len(located)} on the map, {len(countries)} countries")


if __name__ == "__main__":
    build()
