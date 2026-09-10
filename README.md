# Balseiro Alumni Atlas

An interactive map of where **Instituto Balseiro** (Bariloche, Argentina) graduates
live and work — built to help with a job / PhD / master's search: see which
institutions and companies hire Balseiro people, in which countries and fields,
and find names to reach out to.

![overview](docs/screenshot.png)

## How it works

```
scripts/collect_*.py  ─┐
                       ├─►  scripts/build_dataset.py  ─►  site/data/alumni.json  ─►  site/index.html
data/manual_alumni.csv ┘
```

Alumni are gathered from **public, structured sources** (LinkedIn cannot be
scraped and is deliberately not used):

| Source | Contributes |
|--------|-------------|
| [Wikidata](https://www.wikidata.org) | People with `educated at = Instituto Balseiro`, their employers (often with coordinates), fields, photos, Wikipedia links |
| [ORCID](https://orcid.org) | Researchers who list Instituto Balseiro in their **education** history — graduation year, degree, current employer + city/country, keywords |
| Wikipedia | The curated *Alumnado del Instituto Balseiro* category — short bios and portraits |
| `data/manual_alumni.csv` | Anyone **you** add by hand |

`build_dataset.py` merges duplicates (by ORCID iD, then by normalised name),
geocodes each employer via [Nominatim](https://nominatim.org) (cached), classifies
research field and employer type, and writes a single `site/data/alumni.json`.

## Setup

```bash
pip install -r requirements.txt        # just `requests`
python3 scripts/run_all.py             # first run ≈ 5–10 min (geocoding at 1 req/s)
```

Then serve the site (needs a local server — `fetch()` won't work from `file://`):

```bash
cd site && python3 -m http.server 8000
# open http://localhost:8000
```

Re-running is fast because API responses and geocoding live in `data/`
(`data/raw/`, `data/geocode_cache.json`). Use `--fresh` to ignore the caches:

```bash
python3 scripts/run_all.py --fresh
```

## Adding people yourself

Edit `data/manual_alumni.csv` — only `name` is required:

```csv
name,grad_year,degree_program,field,role,employer,city,country,lat,lon,links,notes
María Pérez,2018,Physics,Quantum optics,PhD student,ETH Zürich,Zürich,Switzerland,,,https://maria.example,met at a conference
```

Leave `lat`/`lon` blank and the builder geocodes `employer, city, country`.
If a name matches someone already pulled from Wikidata/ORCID, your fields are
merged in rather than duplicated. Then re-run `python3 scripts/run_all.py`.

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
