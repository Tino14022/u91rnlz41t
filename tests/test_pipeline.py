"""End-to-end build with no network: fake source in, real HTML out."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from dataclasses import replace

from garmin_dashboard.config import DEFAULT_SETTINGS, FatLossGoal, RaceConfig
from garmin_dashboard.domain.health import FetchLog
from garmin_dashboard.pipeline import build_payload
from garmin_dashboard.rendering import build_html
from garmin_dashboard.sources.fake import FakeSource
from garmin_dashboard.sources.garmin import GarminSource
from garmin_dashboard.storage import DictDataStore

ROOT = Path(__file__).resolve().parent.parent
ANCHOR = date(2026, 8, 14)

# The shipped settings follow whatever the athlete is doing now (a bulk, at the
# time of writing). Race mode has to keep working for the next race, so it is
# pinned here rather than left to depend on that.
RACE_SETTINGS = replace(
    DEFAULT_SETTINGS,
    race=RaceConfig(name="Wizz Air Half Marathon", date=date(2026, 10, 4), distance_km=21.1),
    goal=FatLossGoal(),
    bulk=None,
)


def build(api, data_files, log=None, today=ANCHOR, settings=DEFAULT_SETTINGS):
    log = log or FetchLog()
    return build_payload(
        GarminSource(api, log, pause=0),
        DictDataStore(data_files),
        settings,
        log,
        today=today,
        generated_at_time="fixed",
    )


def render(payload) -> str:
    return build_html(
        payload,
        app_template=ROOT / "app_template.html",
        running_template=ROOT / "template.html",
    )


def test_fake_source_satisfies_the_pipeline(data_files):
    """LSP: a substitute source drives the whole build with nothing stubbed out."""
    source = FakeSource(
        runs=[
            {
                "date": ANCHOR.isoformat(),
                "start_time_local": f"{ANCHOR.isoformat()} 07:00:00",
                "distance_km": 12.0,
                "duration_s": 4200,
                "pace_sec_per_km": 350,
                "pace_label": "5:50/km",
                "avg_hr": 150,
                "label": "BASE",
            }
        ],
    )
    log = FetchLog()
    payload = build_payload(
        source,
        DictDataStore(data_files),
        RACE_SETTINGS,
        log,
        today=ANCHOR,
        generated_at_time="fixed",
    )
    assert payload["athlete_name"] == "Test Athlete"
    assert payload["race_plan"]["current_longest_km"] == 12.0
    assert payload["build_health"]["healthy"] is True


def test_build_produces_parseable_html_carrying_the_payload(fake_api, data_files):
    payload = build(fake_api, data_files)
    html = build_html(
        payload,
        app_template=ROOT / "app_template.html",
        running_template=ROOT / "template.html",
    )
    assert "__DASHBOARD_DATA__" not in html
    assert "__RUNNING_TAB_STYLE__" not in html
    assert "__RUNNING_TAB_CONTENT__" not in html
    assert "__RUNNING_TAB_SCRIPT__" not in html

    embedded = re.search(r"const DATA = (\{.*?\});\n", html, re.S)
    assert embedded, "payload was not embedded"
    assert json.loads(embedded.group(1))["athlete_name"] == "Test Athlete"


def test_failing_fetches_are_reported_not_swallowed(data_files):
    from conftest import FakeGarminApi

    api = FakeGarminApi(fail={"get_sleep_daily", "get_rhr_daily"})
    log = FetchLog()
    payload = build(api, data_files, log=log)

    assert payload["sleep_trend"] == []
    health = payload["build_health"]
    assert health["healthy"] is False
    assert health["failed"] == 2
    assert {f["name"] for f in health["failures"]} == {"sleep_trend", "rhr_trend"}


def test_a_healthy_build_says_so(fake_api, data_files):
    payload = build(fake_api, data_files)
    assert payload["build_health"] == {
        "healthy": True,
        "total": payload["build_health"]["total"],
        "failed": 0,
        "failures": [],
    }
    assert payload["build_health"]["total"] > 5


def test_todays_plan_shows_and_a_stale_one_does_not(fake_api, data_files):
    assert build(fake_api, data_files)["workout_plan"]["name"] == "Push Day"
    tomorrow = build(fake_api, data_files, today=ANCHOR + timedelta(days=1))
    assert tomorrow["workout_plan"] is None


def test_race_plan_is_present_and_finishes_at_the_race(fake_api, data_files):
    payload = build(fake_api, data_files, settings=RACE_SETTINGS)
    plan = payload["race_plan"]
    assert plan["race_distance_km"] == 21.1
    assert plan["weeks"][-1]["kind"] == "race"
    assert plan["days_remaining"] == (date(2026, 10, 4) - ANCHOR).days
    assert payload["race"]["name"] == "Wizz Air Half Marathon"
    assert payload["nutrition_view"]["protein_g_per_kg"] == FatLossGoal().protein_g_per_kg
    assert payload["bulk"] is None and payload["eating_target"] is None


def test_with_no_race_booked_the_race_blocks_are_none_not_missing(fake_api, data_files):
    data_files["body_comp"] = [{"date": "2026-08-10", "weight_kg": 93.4, "body_fat_pct": 20.0}]
    payload = build(fake_api, data_files, settings=replace(RACE_SETTINGS, race=None))
    assert payload["race"] is None
    assert payload["race_plan"] is None
    # A cut does not need a race date to be tracked.
    assert payload["fat_loss"]["achievable_by_race"] is False
    assert "race" not in {c["domain"] for c in payload["overview"]["cards"]}


def test_race_mode_still_renders(fake_api, data_files):
    html = render(build(fake_api, data_files, settings=RACE_SETTINGS))
    assert "__DASHBOARD_DATA__" not in html


BULK_DAY = date(2026, 10, 20)


def test_default_settings_build_a_bulk_with_no_race(fake_api, data_files):
    assert DEFAULT_SETTINGS.race is None and DEFAULT_SETTINGS.bulk is not None
    payload = build(fake_api, data_files, today=BULK_DAY)
    assert payload["race"] is None and payload["race_plan"] is None
    assert payload["fat_loss"] is None and payload["eating_budget"] is None
    bulk = payload["bulk"]
    assert bulk["day_number"] == (BULK_DAY - DEFAULT_SETTINGS.bulk.start).days + 1
    assert bulk["creatine"]["day"] == (BULK_DAY - DEFAULT_SETTINGS.bulk.creatine_start).days + 1
    assert {c["domain"] for c in payload["overview"]["cards"]} >= {"bulk"}
    assert "gambling" not in payload and "gambling_view" not in payload


def test_bulk_protein_target_comes_from_the_bulk_goal(fake_api, data_files):
    payload = build(fake_api, data_files, today=BULK_DAY)
    nv = payload["nutrition_view"]
    assert nv["protein_g_per_kg"] == DEFAULT_SETTINGS.bulk.protein_g_per_kg
    assert nv["protein_target_g"] == round(nv["latest_weight_kg"] * DEFAULT_SETTINGS.bulk.protein_g_per_kg)


def test_expenses_and_income_flow_through_to_the_page(fake_api, data_files):
    data_files["expenses"] = [
        {"date": "2026-10-15", "amount_den": 450, "category": "food", "note": "groceries"},
        {"date": "2026-10-19", "amount_den": 1800, "category": "gym"},
    ]
    data_files["income"] = [{"date": "2026-11-04", "amount_den": 55500, "source": "paycheck"}]
    payload = build(fake_api, data_files, today=BULK_DAY)
    ev = payload["expenses_view"]
    assert ev["total_den"] == 2250
    assert ev["paycheck"]["next"]["days_until"] == 15
    assert payload["expenses"] == data_files["expenses"]
    html = render(payload)
    assert "__DASHBOARD_DATA__" not in html


def test_a_build_with_no_money_logged_has_no_expenses_view(fake_api, data_files):
    assert build(fake_api, data_files, today=BULK_DAY)["expenses_view"] is None


def test_the_shipped_split_resolves_to_a_session_or_rest_every_day():
    """Guards the hand-edited split file: a typo in a slot name would silently
    show an empty Workout tab on that weekday."""
    split = json.loads((ROOT / "data" / "training_split.json").read_text(encoding="utf-8"))
    templates = split["templates"]
    assert set(split["schedule"]) == {str(i) for i in range(7)}
    for weekday, slot in split["schedule"].items():
        assert slot == "rest" or templates.get(slot, {}).get("exercises"), f"weekday {weekday}: {slot}"
    for slot in split.get("append_finisher_to", []):
        assert slot in templates
    presets = json.loads((ROOT / "data" / "muscle_presets.json").read_text(encoding="utf-8"))["gym_splits"]
    for slot in set(split["schedule"].values()) - {"rest"}:
        assert slot in presets, f"{slot} has no muscle preset to log it against"


def test_the_shipped_money_files_fit_their_schema():
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import log_entry

    for name in ("expenses", "income"):
        for row in json.loads((ROOT / "data" / f"{name}.json").read_text(encoding="utf-8")):
            log_entry.validate(name, row)


@pytest.mark.parametrize("missing", ["nutrition", "trainings", "muscle_presets", "body_comp"])
def test_build_survives_a_missing_data_file(fake_api, data_files, missing):
    reduced = {k: v for k, v in data_files.items() if k != missing}
    payload = build(fake_api, reduced)
    assert payload["generated_at"] == ANCHOR.isoformat()


def test_empty_store_still_builds(fake_api):
    payload = build(fake_api, {})
    assert payload["nutrition"] == []
    assert payload["training"]["sessions"]
