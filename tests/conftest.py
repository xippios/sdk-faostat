# Core's plugin keeps the default run offline (ADR-0013), runs anyio tests on asyncio and
# serves the family check in tests/test_family.py.
pytest_plugins = ["xippios.core.testing.plugin"]
