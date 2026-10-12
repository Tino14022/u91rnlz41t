# Garmin Training Dashboard

Self-refreshing training dashboard built from live Garmin Connect data plus the hand-logged files in `data/`.

`dashboard.py` pulls sleep, HRV, resting HR, calories burned and activities via `garminconnect`, combines them with logged food, weigh-ins, training and expenses, and writes `index.html`. A GitHub Actions workflow (`.github/workflows/main.yml`) rebuilds it on every push and every 2 hours, and deploys it to GitHub Pages.

## What the page is about

The page follows the goals set in `garmin_dashboard/config.py`, and a goal set to `None` takes its panels with it:

| Setting | Brings |
| --- | --- |
| `bulk=BulkGoal(...)` | The Bulk tab, the eating target, bulk findings on the Overview |
| `race=RaceConfig(...)` | The race countdown, the long-run ladder, the Running tab |
| `goal=FatLossGoal(...)` | The fat-loss panel and the eating budget |

Version 2.0 (October 2026) is set up for a winter bulk: no race, no cut, an upper-body lifting split in `data/training_split.json`, and an Expenses tab in place of the old gambling tracker.

Run locally with `uv run dashboard.py`.
