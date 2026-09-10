"""Run the whole pipeline: collect every source, then rebuild the site dataset.

    python3 scripts/run_all.py            # normal (uses cached API responses)
    python3 scripts/run_all.py --fresh    # ignore caches, re-fetch everything

API responses and geocoding results are cached under data/, so the first run
takes a few minutes (mostly geocoding at 1 req/s) and later runs are quick.
"""
from __future__ import annotations

import shutil
import sys
import time

from common import RAW, DATA
import collect_wikidata
import collect_orcid
import collect_wikipedia
import build_dataset


def main() -> None:
    if "--fresh" in sys.argv:
        print("--fresh: clearing caches")
        shutil.rmtree(RAW, ignore_errors=True)
        RAW.mkdir(parents=True, exist_ok=True)
        (DATA / "geocode_cache.json").unlink(missing_ok=True)

    t0 = time.time()
    for name, fn in [
        ("Wikidata", collect_wikidata.collect),
        ("ORCID", collect_orcid.collect),
        ("Wikipedia", collect_wikipedia.collect),
    ]:
        print(f"\n=== {name} ===")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - one dead source shouldn't stop the rest
            print(f"!! {name} failed: {exc}")

    print("\n=== build ===")
    build_dataset.build()
    print(f"\ndone in {time.time() - t0:.0f}s  ->  open site/index.html")


if __name__ == "__main__":
    main()
