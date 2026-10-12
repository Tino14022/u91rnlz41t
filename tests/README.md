# Tests

Run with `python -m pytest tests/ -q` (needs `pytest` and `tzdata`), or as CI
does it: `uv run --with pytest --with tzdata python -m pytest tests/ -q`.

No Garmin credentials, no network. Every test drives the pipeline through
`FakeGarminApi` (raw Garmin-shaped payloads) or `FakeSource` (already-normalised
rows), which is the point of the source protocols.

| File | What it covers |
| --- | --- |
| `test_domain.py` | Pure transforms: formatting, nutrition, gamification, plan, health, config |
| `test_pipeline.py` | Full offline build in both bulk and race mode, HTML assembly, failure reporting, the shipped data files |
| `test_bulk.py` | The bulk view and the eating target |
| `test_expenses.py` | Spending totals, categories and the paycheck balance |
| `test_regressions.py` | Bugs found along the way |

`test_pipeline.py` pins a `RACE_SETTINGS` of its own. The shipped
`DEFAULT_SETTINGS` follow whatever the athlete is doing now, and race mode has
to keep working for the next race without depending on that.
