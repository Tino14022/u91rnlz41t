# Data files

Hand-maintained via chat with Claude. Each rebuild reads these plus live Garmin data.

## trainings.json
Non-running sessions (gym/padel/football/hike) — running comes from Garmin automatically.
```json
{
  "date": "2026-08-14",
  "type": "gym",              // gym | padel | football | hike | other
  "subtype": "push",          // free text, e.g. a data/muscle_presets.json gym_splits key
  "duration_min": 60,         // omit entirely (not null) to make this an annotation - see below
  "muscle_groups": {"chest": 1.0, "triceps": 0.9},  // 0-1 intensity, ids from muscle_presets.json
  "notes": "bench 4x8@80kg",
  "exercises": [{"name": "Incline DB Press", "target_sets": 4, "target_reps": "8-10", "sets_completed": 4}]  // optional, from a finished workout-plan checklist
}
```
**Annotation vs standalone:** an entry with no `duration_min` key is an annotation — it supplies subtype/muscle_groups/exercises for whatever Garmin activity syncs on that (date, type), and shows as "pending Garmin sync" in the app until that match happens. An entry WITH `duration_min` is a standalone record, shown as-is regardless of Garmin. Default to annotations (omit duration_min) whenever the workout was done wearing the watch — which is the normal case.

## workout_plan.json
The coach-assigned plan for today, rendered as an interactive checklist in the Training tab. Single object, not an array — gets replaced each time a new plan is set.
```json
{
  "date": "2026-08-14",
  "name": "Push Day",
  "exercises": [
    {"name": "Incline DB Press", "target_sets": 4, "target_reps": "8-10"},
    {"name": "Shoulder Press", "target_sets": 3, "target_reps": "8-10"}
  ]
}
```
Only shown in the app when `date` matches the build date. Checklist progress lives in the browser's localStorage, not here — when the user finishes and pastes the summary back, log the result into `trainings.json` as an annotation (see above), using the `exercises` field to capture what was actually completed. If today's date isn't in here, the Workout tab falls back to `training_split.json` below rather than showing nothing — so this file is only needed for a one-off override of what the standing split would otherwise show today.

## training_split.json
The standing weekly split — a fixed rotation, not something re-asked each morning. Single object.
```json
{
  "schedule": {"0": "push", "1": "pull", "2": "arms_shoulders", "3": "rest", "4": "push", "5": "pull", "6": "rest"},
  "append_finisher_to": ["push", "pull"],
  "templates": {
    "push": {"name": "Upper Push", "exercises": [{"name": "Incline Dumbbell Bench Press", "target_sets": 4, "target_reps": "8-10"}]},
    "abs_finisher": {"name": "Abs Finisher", "exercises": [{"name": "Plank", "target_sets": 3, "target_reps": "60 sec"}]}
  }
}
```
`schedule` keys are Python `date.weekday()` ints (Mon=0..Sun=6). A slot is a lifting day when its `templates` entry lists `exercises` (same shape as `workout_plan.json`) — the slot name itself is free, so a new session type needs no code change. A template with a plain `note` instead is a day with no fixed reps, `rest` is a rest day, and `long_run` / `light_run` are run days. `append_finisher_to` names which slots get the `abs_finisher` exercises tacked onto the end. Every lifting slot should also have a `gym_splits` entry of the same name in `muscle_presets.json`, so the session can be logged against muscle groups.

The Bulk tab counts the week's planned lifting days from this file, and marks a day done when a gym session (Garmin-synced or logged) lands on it. Edit this by hand (or ask Claude to) when the split itself changes — it's not something the daily check-ins write to.

## race_plan_workouts.json
The structured running sessions for the half-marathon build, pushed to Garmin Connect by `scripts/push_workouts_to_garmin.py`. Not read by the dashboard build — this file exists to drive the watch.
```json
{
  "name_prefix": "HM26",
  "paces": {"easy": [385, 400], "tempo": [335, 345]},   // [fast, slow] seconds per km
  "sessions": [
    {"date": "2026-09-05", "name": "Tempo 2x2km", "steps": [
      {"kind": "warmup", "distance_m": 1500, "pace": "easy"},
      {"kind": "run", "distance_m": 2000, "pace": "tempo"},
      {"kind": "recover", "seconds": 90},
      {"kind": "repeat", "times": 5, "steps": [{"kind": "run", "distance_m": 800, "pace": "tempo"}]},
      {"kind": "cooldown", "distance_m": 1000, "pace": "easy"}
    ]}
  ]
}
```
Step kinds: `warmup`, `run`, `recover`, `cooldown` (each takes either `distance_m` or `seconds`, plus an optional `pace` key naming an entry in `paces`), and `repeat` (takes `times` and nested `steps`). Rest days are simply absent — nothing is pushed for them.

Change the plan by editing this file, then re-run `python scripts/push_workouts_to_garmin.py --push --replace`, which deletes the previously-pushed workouts sharing `name_prefix` before recreating them. Run it without `--push` first for a dry run. Requires `pip install garminconnect` and your own Garmin login (env `GARMIN_EMAIL`/`GARMIN_PASSWORD` or an interactive prompt); the CI build neither needs nor runs this.

## nutrition.json
```json
{
  "date": "2026-08-14",
  "meal": "lunch",             // breakfast | lunch | dinner | snack
  "description": "one plate of lasagna",
  "grams": null,               // if the user gave a precise weight instead
  "calories": 650,
  "protein_g": 30,
  "carbs_g": 55,
  "fat_g": 32
}
```
Macros are Claude's estimate from the description, made at logging time.

## body_comp.json
Mi Scale readings.
```json
{
  "date": "2026-08-14",
  "weight_kg": 95.0,
  "body_fat_pct": 22.5,
  "muscle_mass_kg": 68.0,
  "water_pct": 55.0,
  "bone_mass_kg": 3.2,
  "visceral_fat": 12,
  "bmr": 1950
}
```
Only include fields the user actually provided.

## lifestyle.json
Factors that measurably affect sleep/recovery but aren't training or food.
```json
{
  "date": "2026-08-14",
  "cigarettes_level": "usual",   // low (0-5) | usual (5-15) | alot (15-20/one pack) | extreme (more than a pack) | null
  "alcohol_drinks": 0,           // count, null if not mentioned that day
  "cannabis_used": false,        // true/false/null
  "vacation": false,             // true if this day wasn't tracked because of travel/vacation
  "creatine": false,             // only ever logged as false, for a day the dose was missed
  "notes": null
}
```
One entry per day. Cigarettes default to "usual" going forward once the user gives a baseline — only log a different level when they mention a day was notably different. Don't fabricate entries for days never mentioned; leave the day absent rather than guessing.

`vacation: true` marks a day as deliberately untracked rather than missing — the Nutrition tab's calendar shows a distinct beach icon for these days instead of reading as a logging gap.

`creatine: false` marks a missed dose. Creatine is assumed taken every day from the start date in `garmin_dashboard/config.py`, so only the misses are logged; each one pushes the "fully loaded" date on the Bulk tab back a day.

## expenses.json
Money out, in MKD denars.
```json
{
  "date": "2026-10-13",
  "amount_den": 450,
  "category": "food",          // free text, lower-cased and merged on the page; "other" when omitted
  "note": "groceries"          // optional
}
```
Several entries per day are fine and are summed. A refund is a negative `amount_den`. Keep categories few and consistent (food, eating out, rent, bills, gym, supplements, transport, shopping, fun) — the "Where it went" bars are only useful if the same thing lands in the same bucket every time.

## income.json
Money in.
```json
{
  "date": "2026-11-04",
  "amount_den": 55500,
  "source": "paycheck"
}
```
An entry dated in the future is an *expected* paycheck: the Expenses tab counts down to it. Once its date arrives it becomes the current paycheck, and the tab shows what is left of it and what that allows per day until the next entry (or, with none on file, until the same day next month). Log the next paycheck ahead of time to keep that end date exact.

## archive/
Files no longer read by the build. `archive/gambling.json` is the log from the gambling tracker that the Expenses tab replaced in October 2026; it is kept for the record and nothing renders it.
