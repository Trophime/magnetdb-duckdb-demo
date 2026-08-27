"""
parallel.py
===========
Generic thread-pool helper for I/O-bound per-row file processing (TDMS /
pupitre reads via python_magnetrun) shared across populate/compute scripts.

Intended shape for callers: fetch everything needed from the DB once
(single-threaded), run a *pure* per-row function concurrently via
``parallel_map`` (no DB access inside the worker — DuckDB connections are
not safe to share across threads), then apply DB writes sequentially back
in the calling thread.

Public API
----------
    parallel_map(items, worker, max_workers, desc) -> list
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    items: Sequence[T],
    worker: Callable[[T], R],
    max_workers: int = 8,
    desc: str | None = None,
) -> list[R]:
    """Run ``worker(item)`` for each item on a thread pool.

    Parameters
    ----------
    items : Sequence
        Inputs, one per task.
    worker : Callable[[T], R]
        Pure function with no shared mutable state (e.g. no DB connection)
        — safe to run concurrently. I/O-bound work (file reads) benefits
        most; CPU-bound work will not scale past one core due to the GIL.
    max_workers : int, optional
        Thread pool size (default 8).
    desc : str, optional
        When given, prints a running ``"desc: n/total"`` progress line as
        results complete.

    Returns
    -------
    list
        Results in the same order as *items* (not completion order).
    """
    if not items:
        return []

    results: list[R] = [None] * len(items)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, item): i for i, item in enumerate(items)}
        for done, future in enumerate(as_completed(futures), start=1):
            i = futures[future]
            results[i] = future.result()
            if desc:
                print(f"  {desc}: {done}/{len(items)}", end="\r")
    if desc:
        print()
    return results
