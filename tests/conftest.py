"""Keep provider marker selection from implicitly enabling paid checks."""
import pytest


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    # CLI -m normally replaces the configured expression. Require operators to
    # explicitly remove the repository's not-live default as well.
    if 'not live' not in config.getini('addopts'):
        return
    deselected = [item for item in items if item.get_closest_marker('live') is not None]
    if deselected:
        items[:] = [item for item in items if item.get_closest_marker('live') is None]
        config.hook.pytest_deselected(items=deselected)
