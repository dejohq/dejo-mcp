"""Does knowing a site make a DIFFERENT task on it cheaper?

    .venv/Scripts/python -u benchmarks/benchmark_site_memory.py --keep <folder> --out <file>

`benchmark_learning.py` measures the same task twice. This measures a second, different task
on a site Dejo has already walked. The real bench has two tasks on most sites (A and B), so
for each such site:

- **cold**: B on an empty memory, the way any first visit starts;
- **first**: A on a new memory, so Dejo learns the site;
- **warm**: B on that same memory, after A.

warm against cold is the whole question. Both runs of B are the same task, model, tool and
day; the only difference is what Dejo already knows about the site. A warm run that answers
WRONG counts against Dejo, never for it: if B were mistaken for A and A's route replayed,
that would show up here as a wrong answer.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import date
from pathlib import Path
from statistics import median

from benchmark_agents import COOLDOWN_S, EFFORT, MODEL
from benchmark_learning import (
    REAL_TASKS,
    Attempt,
    Task,
    _dejo_version,
    _git_commit,
    session,
    show,
    trails_in,
)

HERE = Path(__file__).parent
TOOL = "dejo"


def pairs() -> list[tuple[Task, Task]]:
    """(A, B) for every site with at least two tasks: its first two, in bench order."""
    by_site: dict[str, list[Task]] = defaultdict(list)
    for task in REAL_TASKS:
        by_site[task.site.domain].append(task)
    return [(tasks[0], tasks[1]) for tasks in by_site.values() if len(tasks) >= 2]


def run_pair(first: Task, second: Task, keep: Path) -> list[Attempt]:
    """B cold, then A and B on one shared memory. Each memory lives in its own folder."""
    cold_folder = keep / f"{second.name}-cold"
    warm_folder = keep / f"{first.name}-then-{second.name}"
    for folder in (cold_folder, warm_folder):
        folder.mkdir(parents=True, exist_ok=True)

    cold = session(TOOL, second, 1, "cold", str(cold_folder / "memory.db"), cold_folder)
    time.sleep(COOLDOWN_S)
    shared = str(warm_folder / "memory.db")
    learned = session(TOOL, first, 1, "first", shared, warm_folder)
    learned.trails = trails_in(shared)
    time.sleep(COOLDOWN_S)
    warm = session(TOOL, second, 1, "warm", shared, warm_folder)
    warm.trails = trails_in(shared)
    return [cold, learned, warm]


def summary(attempts: list[dict]) -> str:
    """Cold against warm for B, over the sites where both runs of B answered right."""
    by_task: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in attempts:
        if row["phase"] in ("cold", "warm"):
            by_task[row["task"]][row["phase"]] = row
    both = [p for p in by_task.values() if "cold" in p and "warm" in p]
    right = [p for p in both if p["cold"]["correct"] and p["warm"]["correct"]]
    lines = [
        f"pairs measured: {len(both)}; cold right {sum(p['cold']['correct'] for p in both)}, "
        f"warm right {sum(p['warm']['correct'] for p in both)}"
    ]
    if right:
        for key in ("tokens", "turns", "seconds"):
            cold = [p["cold"][key] for p in right]
            warm = [p["warm"][key] for p in right]
            lines.append(
                f"{key} (both right, n={len(right)}): cold avg {sum(cold) / len(cold):,.0f} "
                f"median {median(cold):,.0f} | warm avg {sum(warm) / len(warm):,.0f} "
                f"median {median(warm):,.0f}"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", required=True, help="folder for every run's memory and log")
    parser.add_argument("--site", default="", help="only sites whose domain contains this")
    parser.add_argument("--out", default="", help="results file (default: dated, beside this)")
    args = parser.parse_args()

    chosen = [(a, b) for a, b in pairs() if args.site in a.site.domain]
    if not chosen:
        parser.error(f"no site matching {args.site!r}")
    keep = Path(args.keep)
    out = Path(args.out) if args.out else HERE / f"benchmark-site-memory-{date.today()}.json"
    meta = {
        "date": str(date.today()),
        "model": MODEL,
        "effort": EFFORT,
        "dejo": _dejo_version(),
        "commit": _git_commit(),
    }
    attempts: list[Attempt] = []
    for first, second in chosen:
        if attempts:
            time.sleep(COOLDOWN_S)
        attempts.extend(run_pair(first, second, keep))
        show(attempts[-3:])
        # Written after every pair, so a sweep stopped halfway keeps what it paid for.
        rows = [asdict(a) for a in attempts]
        out.write_text(json.dumps({"meta": meta, "runs": rows}, indent=1), encoding="utf-8")
    print("\n" + summary([asdict(a) for a in attempts]))
    print(f"\n  Written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
