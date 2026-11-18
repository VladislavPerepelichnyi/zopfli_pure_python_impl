"""pytest configuration for the zopfli_pure test suite.

* Puts the repository root and ``tests/`` on ``sys.path`` so that
  ``import zopfli_pure``, ``import corpus`` and ``import ref`` work however
  pytest is invoked.
* Tests marked ``@pytest.mark.slow`` are skipped unless the environment
  variable ``ZOPFLI_PURE_SLOW`` is set to a non-zero value (``1``).
  ``ZOPFLI_PURE_SLOW=2`` additionally enables the very large inputs
  (> 1 MB, ``@pytest.mark.huge``).
* Hypothesis profiles: ``default`` (few examples, no deadline) and ``thorough``
  (select with ``--hypothesis-profile=thorough`` or
  ``ZOPFLI_PURE_HYPOTHESIS=thorough``).
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def slow_level():
    try:
        return int(os.environ.get("ZOPFLI_PURE_SLOW", "0") or 0)
    except ValueError:
        return 1


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: long-running tests (large inputs);"
                            " run with ZOPFLI_PURE_SLOW=1")
    config.addinivalue_line("markers", "huge: inputs > 1 MB; run with"
                            " ZOPFLI_PURE_SLOW=2")
    config.addinivalue_line("markers", "oracle: needs py-zopfli or the C"
                            " reference library")


def pytest_collection_modifyitems(config, items):
    level = slow_level()
    skip_slow = pytest.mark.skip(reason="slow: set ZOPFLI_PURE_SLOW=1 to run")
    skip_huge = pytest.mark.skip(reason="huge: set ZOPFLI_PURE_SLOW=2 to run")
    for item in items:
        if "huge" in item.keywords and level < 2:
            item.add_marker(skip_huge)
        elif "slow" in item.keywords and level < 1:
            item.add_marker(skip_slow)


try:
    from hypothesis import HealthCheck, settings

    settings.register_profile(
        "default", max_examples=40, deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
    settings.register_profile(
        "thorough", max_examples=500, deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
    settings.load_profile(os.environ.get("ZOPFLI_PURE_HYPOTHESIS", "default"))
except ImportError:  # pragma: no cover
    pass
