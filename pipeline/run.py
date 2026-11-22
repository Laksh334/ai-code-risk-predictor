"""A4 - Pipeline entry point.

    python -m pipeline.run scan https://github.com/psf/requests      # features of today's code
    python -m pipeline.run dataset                                   # training set from repos.txt
    python -m pipeline.run refresh                                   # update everything once
    python -m pipeline.run refresh --every 360                       # ...and keep doing it every 6h

`refresh` is the "continuous feed" for the ML engineer: it pulls every tracked repo, parses
only the new commits (cache), writes fresh per-repo features and rebuilds the dataset.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline.dataset import build_dataset, summarize
from pipeline.scanner import scan_repository
from pipeline.paths import DATA_DIR

log = logging.getLogger("pipeline")
OUT = DATA_DIR / "processed"


def read_repo_list(path: str | Path) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def cmd_scan(sources: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for src in sources:
        started = time.perf_counter()
        try:
            result = scan_repository(src)
        except Exception:  # one bad repo must not stop the others
            log.exception("Scan failed for %s", src)
            continue
        target = OUT / f"{result.repo}_latest_features.csv"
        result.features.to_csv(target, index=False)
        s = result.summary
        log.info("%s @ %s: %d files in %.1fs -> %s", s["repo"], s["commit_sha"][:10], s["files"],
                 time.perf_counter() - started, target)


def cmd_dataset(sources: list[str], interval: int, horizon: int) -> pd.DataFrame | None:
    frames = []
    for src in sources:
        try:
            frames.append(build_dataset(src, interval, horizon))
        except Exception:
            log.exception("Dataset build failed for %s", src)
    frames = [f for f in frames if not f.empty]
    if not frames:
        log.error("No data produced")
        return None
    df = pd.concat(frames, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "dataset.csv"
    df.to_csv(target, index=False)
    log.info("dataset: %d rows from %d repos, %d snapshots, %.1f%% bug-prone -> %s",
             len(df), df["repo"].nunique(), len(summarize(df)), 100 * df["label_bug_prone"].mean(), target)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Code risk data pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "dataset", "refresh"):
        p = sub.add_parser(name)
        p.add_argument("sources", nargs="*", help="GitHub URLs / local paths (default: repos file)")
        p.add_argument("--repos-file", default="pipeline/repos.txt")
        if name != "scan":
            p.add_argument("--interval", type=int, default=6, help="months between snapshots")
            p.add_argument("--horizon", type=int, default=6, help="months ahead for labels")
        if name == "refresh":
            p.add_argument("--every", type=int, help="repeat every N minutes (Ctrl+C to stop)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    sources = args.sources or read_repo_list(args.repos_file)

    if args.cmd == "scan":
        cmd_scan(sources)
    elif args.cmd == "dataset":
        cmd_dataset(sources, args.interval, args.horizon)
    else:
        while True:
            log.info("refresh started (%d repos)", len(sources))
            cmd_scan(sources)  # pulls + updates caches + latest features
            cmd_dataset(sources, args.interval, args.horizon)  # reuses the caches: fast
            if not args.every:
                break
            log.info("next refresh at %s", datetime.fromtimestamp(
                time.time() + args.every * 60, tz=timezone.utc).strftime("%H:%M UTC"))
            time.sleep(args.every * 60)


if __name__ == "__main__":
    main()
