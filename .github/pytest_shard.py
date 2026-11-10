"""Runs one slice of a test suite, so CI can spread it over several machines.

`PYTEST_SHARD=2/4` keeps the 2nd, 6th, 10th... collected test. Taking every Nth test instead
of whole files spreads the slow files (the ones that wait out real timeouts) over all slices.
Every fixture here is per test or per session, so a slice needs nothing from another one.
Without the variable, nothing changes. CI loads it with `-p pytest_shard`.
"""

import os


def pytest_collection_modifyitems(config, items):
    shard = os.environ.get("PYTEST_SHARD")
    if not shard:
        return
    index, total = (int(n) for n in shard.split("/"))
    assert 1 <= index <= total, f"PYTEST_SHARD={shard} is not a slice like 2/4"
    kept = [item for n, item in enumerate(items) if n % total == index - 1]
    config.hook.pytest_deselected(
        items=[item for n, item in enumerate(items) if n % total != index - 1]
    )
    items[:] = kept
