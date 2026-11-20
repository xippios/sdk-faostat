# Core's plugin keeps the default run offline (sdk-core ADR-0035), runs anyio tests on
# asyncio and serves the family check in tests/test_family.py.
pytest_plugins = ["xippios.core.testing.plugin"]
