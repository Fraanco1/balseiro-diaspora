# Balseiro Alumni Atlas

An interactive map of where **Instituto Balseiro** (Bariloche, Argentina) graduates
live and work — built to help with a job / PhD / master's search: see which
institutions and companies hire Balseiro people, in which countries and fields,
and find names to reach out to.

## How it works

```
scripts/collect_*.py  ─┐
data/manual_alumni.csv ├─►  scripts/build_dataset.py  ─►  site/data/alumni.json  ─►  site/index.html
data/review_candidates.csv ┘        ▲
                          data/blocklist.txt
```

Alumni are gathered from **public, structured sources** (LinkedIn cannot be
scraped and is deliberately not used):

| Source | Contributes | Confidence |
|--------|-------------|------------|
| [Wikidata](https://www.wikidata.org) | `educated at` / `employer` / `affiliation` = Instituto Balseiro; employers (often with coordinates), fields, photos, Wikipedia links | confirmed |
| [ORCID](https://orcid.org) | Anyone with Instituto Balseiro in their **education** history — grad year, degree, current employer + city/country, keywords. Candidate iDs come from ORCID's own search **and** from OpenAlex. | confirmed |
| [OpenAlex](https://openalex.org) | ~2,900 authors who ever published with a Balseiro affiliation. ORCID ones are verified above; high-scoring ORCID-less ones are added directly; the rest go to a review queue. Also adds publication counts, h-index and research concepts to everyone. | inferred (unless verified) |
| Wikipedia | Curated *Alumnado / Profesores del Instituto Balseiro* categories — bios and portraits | confirmed |
| RICABIB thesis repo (opt-in, run from Argentina) | Author + year + title of every IB thesis — the authoritative roster | confirmed |
| `data/manual_alumni.csv` | Anyone **you** add by hand | confirmed |

`build_dataset.py` merges duplicates (by ORCID iD, then by normalised name),
resolves each person's location from Wikidata/OpenAlex coordinates or
[Nominatim](https://nominatim.org) geocoding (cached), classifies research field
and employer sector, tags `confidence`, and writes a single `site/data/alumni.json`.

## Setup

```bash
pip install -r requirements.txt        # just `requests`
python3 scripts/run_all.py             # first run ≈ 15–20 min (ORCID verification + geocoding)
python3 serve.py                       # -> http://localhost:8000  (fetch() needs http, not file://)
```

Re-running is fast because API responses and geocoding live in `data/`
(`data/raw/`, `data/geocode_cache.json`). Use `--fresh` to ignore the caches;
add `--ricabib` to also harvest the thesis repository (only works from Argentina):

```bash
python3 scripts/run_all.py --fresh
python3 scripts/run_all.py --ricabib
```

## Growing the database

| Want more… | Do this |
|---|---|
| **people, automatically** | Already maxed on Wikidata/ORCID/OpenAlex. Re-run `run_all.py` periodically to pick up newly-published profiles. |
| **inferred people confirmed** | Edit `data/review_candidates.csv` (below). |
| **people you know personally** | Edit `data/manual_alumni.csv` (below) — highest precision. Browsing LinkedIn's "Instituto Balseiro" alumni page while logged in and copying names in is fine; automated scraping is not. |
| **the authoritative graduate roster** | `python3 scripts/collect_ricabib.py` from an Argentine connection (see its header — you may need to adjust `BASE`). |
| **fewer false positives** | Add names to `data/blocklist.txt`. |

### `data/manual_alumni.csv` — only `name` is required

```csv
name,grad_year,degree_program,field,role,employer,city,country,lat,lon,links,notes
María Pérez,2018,Physics,Quantum optics,PhD student,ETH Zürich,Zürich,Switzerland,,,https://maria.example,met at a conference
```

Leave `lat`/`lon` blank and the builder geocodes `employer, city, country`.
If a name matches someone already pulled from another source, your fields are
merged in rather than duplicated. Then re-run `python3 scripts/run_all.py`.

### `data/review_candidates.csv` — vetting the inferred entries

Every run regenerates this file with mid-confidence people OpenAlex thinks
studied at Balseiro but that couldn't be auto-verified. For anyone real, set
`keep` to `y` (and fill `city`/`country` or `lat`,`lon` if the listed
institution looks wrong). Your `keep` marks are preserved across future runs.

## The website

- **Map** — clustered markers; blue = currently in Argentina, amber = abroad.
  Click a marker for role, employer, graduation year, field and links
  (Wikipedia / ORCID / Google Scholar / homepage).
- **Filters** — text search; Argentina / Abroad toggle; facets for research field,
  employer type, degree program, graduation decade and country, each with live counts.
- **Insights** — share working abroad, top destination countries, institutions
  employing 2+ alumni (outreach targets), field and employer-type breakdowns,
  graduations by decade. Bars are clickable.
- **List** — sortable table of everyone, including people with no mapped location.

Pure static files (Leaflet + Leaflet.markercluster from CDN, CARTO basemap).
Deploy by copying `site/` to GitHub Pages, Netlify, etc.

## Caveats

Coverage is **partial** and skewed toward people with an academic/research web
presence — early graduates, and those who went into private industry or
Argentina's nuclear sector without an ORCID, are under-represented. Locations are
the most recent employer on record and can be stale. Treat it as a research
starting point, not a directory.

## Data & licensing

Wikidata (CC0), ORCID public records (CC0), Wikipedia (CC BY-SA), geocoding ©
OpenStreetMap contributors (ODbL). Respect each source's terms if you
redistribute the compiled dataset.
