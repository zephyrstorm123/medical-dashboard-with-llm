"""Smoke test: proves pytest is wired up and the app package imports.

It does almost nothing on purpose. If this fails, the problem is the
environment (wrong folder, venv not active), not our code.
"""

import importlib


def test_app_packages_import():
    for name in ["app.security", "app.db", "app.api", "app.services", "app.workers"]:
        assert importlib.import_module(name) is not None
