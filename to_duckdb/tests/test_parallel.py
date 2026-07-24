"""Unit tests for parallel.py's parallel_map()."""

import time

from parallel import parallel_map


def test_parallel_map_empty_returns_empty_list():
    assert parallel_map([], lambda x: x * 2) == []


def test_parallel_map_applies_worker_to_every_item():
    assert parallel_map([1, 2, 3, 4], lambda x: x * 2) == [2, 4, 6, 8]


def test_parallel_map_preserves_input_order_regardless_of_completion_order():
    # Earlier items sleep longer, so they'd finish last if order weren't preserved.
    delays = [0.06, 0.04, 0.02, 0.0]

    def worker(i):
        time.sleep(delays[i])
        return i

    assert parallel_map(list(range(len(delays))), worker, max_workers=4) == [0, 1, 2, 3]


def test_parallel_map_runs_concurrently():
    n = 6
    delay = 0.05

    def worker(_i):
        time.sleep(delay)
        return True

    start = time.perf_counter()
    results = parallel_map(list(range(n)), worker, max_workers=n)
    elapsed = time.perf_counter() - start

    assert results == [True] * n
    # Sequential would take ~n * delay; concurrent should be close to one delay.
    assert elapsed < (n * delay) / 2
