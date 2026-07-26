# Backend test modes

The backend suite contains deterministic tests and tests that call a separately
running DocSync API deployment.

Run the deterministic suite used for normal development and CI:

```bash
python -m pytest -q backend/tests
```

Run the live API tests only when the intended deployment is running and its
configuration is appropriate for the assertions:

```bash
python -m pytest -q backend/tests --run-live-api
```

The same opt-in can be enabled with:

```bash
RUN_LIVE_API_TESTS=true python -m pytest -q backend/tests
```

`backend/tests/conftest.py` also forces `DEMO_MODE=true` during collection so
BC sandbox unit tests use their built-in mock records instead of inheriting the
host's production Business Central configuration.
