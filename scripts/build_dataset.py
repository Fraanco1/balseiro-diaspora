"""Merge every source into a single site/data/alumni.json for the website.

Steps
-----
1. Load the raw per-source files (Wikidata, ORCID, Wikipedia) + the optional
   hand-maintained data/manual_alumni.csv.
2. Merge records that refer to the same person (by ORCID iD, then by a
   normalised name key).
3. Resolve each person's *current* location (institution -> lat/lon) using
   coordinates already in Wikidata, otherwise geocoding "<org>, <city>,
   <country>" via Nominatim (cached in data/geocode_cache.json).
4. Classify discipline + employment sector from keywords.
5. Write site/data/alumni.json (list + meta) — the only file the site loads.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re

from common import (DATA, SITE_DATA, ROOT, geocode_many, name_key, strip_accents)

RAW_FILES = {
    "wikidata": DATA / "raw" / "wikidata_alumni.json",
    "orcid": DATA / "raw" / "orcid_alumni.json",
    "wikipedia": DATA / "raw" / "wikipedia_alumni.json",
}
MANUAL_CSV = DATA / "manual_alumni.csv"

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
    ("Condensed matter & materials", r"condensed matter|solid[- ]state|material science|materials science|superconduct|magnetism|nanostructur|nanoscien|nanotechnolog|spintron|semiconductor|thin film|crystal|metallurg|corrosion|graphene"),
    ("Astrophysics & astronomy", r"astrophys|astronom|cosmic ray|galax|stellar|exoplanet|planetary scien|solar physic"),
    ("Nuclear engineering & energy", r"nuclear|reactor|fission|neutron|radioprotection|radiation protection|fuel cycle|radioisotop|nucleoelectr"),
    ("Plasma & fusion physics", r"plasma|tokamak|fusion|magnetohydro"),
    ("Atmospheric, earth & environment", r"atmospher|climate|meteorolog|geophys|environment|oceanograph|hydrolog|glaciolog|earth scien|renewable energ|solar energ|wind energ"),
    ("Biophysics, medical & health physics", r"biophys|medical physic|health physic|radiotherap|dosimetr|biomedic|neuroscien|molecular biolog|medicine|clinical|hospital|health"),
    ("Photonics & optics", r"photonic|optic|laser|plasmonic|spectroscop|holograph"),
    ("Computer science, data & AI", r"machine learning|artificial intelligence|deep learning|neural network|computer scien|data scien|data analy|software|algorithm|comput\w* vision|blockchain|cryptograph|informatic"),
    ("Mechanical & aerospace engineering", r"mechanical eng|aerospace|aeronaut|fluid dynam|fluid mechanic|thermodynam|combustion|turbomachin|structural eng|manufacturing"),
    ("Electronics, control & telecom", r"electronic|telecommunicat|signal processing|antenna|microwave|fpga|embedded system|control system|instrumentation|circuit"),
    ("Mathematics & statistics", r"mathematic|statistic|probability|topolog|geometry|number theory|differential equation|dynamical system"),
    ("Complex systems & statistical physics", r"complex system|statistical (physic|mechanic)|network scien|econophys|nonlinear dynam|agent[- ]based|sociophys"),
    ("Economics, finance & policy", r"economic|finance|financial|quantitative analyst|science polic|management|consult"),
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


def _classify(text: str, rules, default=None):
    t = strip_accents(text or "").lower()
    for label, pattern in rules:
        if re.search(pattern, t):
            return label
    return default


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
        "_wd_employers": [], "_orcid_current": None,
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
        rec["_wd_employers"] = p.get("employers") or []
        if p.get("orcid"):
            by_orcid[p["orcid"]] = key
        by_name.setdefault(name_key(p["name"]), key)


def _merge_orcid(idx, by_orcid, by_name):
    for p in json.loads(RAW_FILES["orcid"].read_text(encoding="utf-8")):
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


def _merge_manual(idx, by_name):
    if not MANUAL_CSV.exists():
        return 0
    n = 0
    with MANUAL_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            # csv.DictReader yields None for short rows and missing trailing
            # columns, so normalise every value to a stripped string first.
            row = {k: (v or "").strip() for k, v in row.items() if k}
            if not row.get("name") or row["name"].lstrip().startswith("#"):
                continue
            nk = name_key(row["name"])
            key = by_name.get(nk) or ("name", nk)
            rec = idx.setdefault(key, _blank_person())
            rec["name"] = rec["name"] or row["name"]
            rec["sources"].add("manual")
            for field in ("grad_year", "role", "degree_program", "description"):
                if row.get(field):
                    rec[field] = row[field]
            if row.get("field"):
                rec["fields"].add(row["field"])
            for u in re.split(r"[;\s]+", row.get("links", "")):
                if u:
                    rec["urls"].add(u)
            if row.get("employer"):
                rec["employer_name"] = row["employer"]
            if row.get("city"):
                rec["employer_city"] = row["city"]
            if row.get("country"):
                rec["employer_country"] = row["country"]
            try:
                if row.get("lat") and row.get("lon"):
                    rec["lat"], rec["lon"] = float(row["lat"]), float(row["lon"])
            except ValueError:
                pass
            n += 1
    return n


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

    _merge_wikidata(idx, by_orcid, by_name)
    _merge_orcid(idx, by_orcid, by_name)
    _merge_wikipedia(idx, by_orcid, by_name)
    n_manual = _merge_manual(idx, by_name)
    print(f"merged: {len(idx)} distinct people "
          f"(wikidata+orcid+wikipedia+{n_manual} manual rows)")

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
        program = rec["degree_program"] or _classify(
            " ".join(rec["degrees"]) + " " + (rec["description"] or ""), DEGREE_PROGRAM_RULES)

        # Classify the *research field* from research signals first; only fall
        # back to a coarse bucket from the Balseiro degree if nothing matched.
        research_blob = " ".join([
            " ".join(rec["fields"]), " ".join(rec["keywords"]),
            " ".join(rec["occupations"]), rec["description"] or "",
            rec["biography"] or "", rec["employer_name"] or "",
        ])
        discipline = _classify(research_blob, DISCIPLINE_RULES, default=None)
        if not discipline:
            discipline = _classify(" ".join(rec["degrees"]), DISCIPLINE_RULES, default=None)
        if not discipline:
            discipline = PROGRAM_TO_DISCIPLINE.get(program, "Not specified")

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
            "grad_year": gy,
            "grad_decade": (gy // 10 * 10) if gy else None,
            "birth_year": rec["birth_year"],
            "deceased": bool(rec["death_year"]),
            "keywords": sorted(rec["keywords"])[:12] or None,
            "fields": sorted(rec["fields"]) or None,
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
            "sources": {
                s: sum(1 for p in out if s in p["sources"])
                for s in ("wikidata", "orcid", "wikipedia", "manual")
            },
            "disclaimer": (
                "Compiled automatically from public data (Wikidata, ORCID, "
                "Wikipedia). Coverage is partial and skewed toward people with "
                "an academic/research web presence. Locations are the current or "
                "most recent employer on record and may be out of date."
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
