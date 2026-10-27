"""python -m lab.features build     cache every finished day of the recorded tables, then coverage.json
python -m lab.features coverage  only coverage.json
python -m lab.features report    coverage and rank IC of every feature (reports/feature_store_d3/, and
                                 results/feature_store_d3.md with PYTHIA_RESULTS)"""

from __future__ import annotations

import argparse
import time

from .. import report as rep
from . import registry as R
from . import store, study


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lab.features")
    ap.add_argument("command", nargs="?", default="build", choices=["build", "coverage", "report"])
    ap.add_argument("--until", help="build days before this UTC date (default today)")
    a = ap.parse_args(argv)
    t0 = time.time()
    if a.command == "build":
        res = store.build(until=a.until)
        print(f"built {res}")
        R.clear()
    if a.command in ("build", "coverage"):
        cov = study.coverage()
        p = store.write_coverage({"updated_us": int(time.time() * 1e6), "features": cov})
        print(f"coverage of {sum(1 for c in cov.values() if c['first_us'])} of {len(cov)} features in {p}, "
              f"{time.time() - t0:.0f} s")
    if a.command == "report":
        res = study.run()
        rep.write("feature_store_d3", study.report(res), res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
