"""The bulk view: timeline, weight against the gain band, intake against the
eating target, creatine loading, and the week's lifting.

The two ways a bulk fails quietly — not eating enough, or gaining too fast —
both have to surface as findings, and neither may fire off too little data.
"""
from __future__ import annotations

from datetime import date, timedelta

from garmin_dashboard.config import BulkGoal
from garmin_dashboard.domain.bulk import build_bulk_view
from garmin_dashboard.domain.fuelling import build_eating_target

START = date(2026, 10, 12)
GOAL = BulkGoal(start=START, end=date(2027, 3, 1), creatine_start=date(2026, 10, 6))

SPLIT = {
    "schedule": {"0": "push", "1": "pull", "2": "arms_shoulders", "3": "rest", "4": "push", "5": "pull", "6": "rest"},
    "templates": {
        "push": {"name": "Upper Push", "exercises": [{"name": "Bench", "target_sets": 4, "target_reps": "8-10"}]},
        "pull": {"name": "Upper Pull", "exercises": [{"name": "Row", "target_sets": 4, "target_reps": "8-10"}]},
        "arms_shoulders": {"name": "Arms & Shoulders", "exercises": [{"name": "Curl", "target_sets": 3, "target_reps": "10"}]},
    },
}


def day(n: int) -> date:
    """n days into the bulk; day(0) is the start."""
    return START + timedelta(days=n)


def scan(n: int, kg: float, bf: float | None = None) -> dict:
    row = {"date": day(n).isoformat(), "weight_kg": kg}
    if bf is not None:
        row["body_fat_pct"] = bf
    return row


def food(d: date, kcal: float, protein: float = 190) -> dict:
    return {"date": d.isoformat(), "calories": kcal, "protein_g": protein}


def view(today: date, *, goal=GOAL, eating_target=3100, protein_target=190, **payload):
    payload.setdefault("eating_target", {"daily_target_kcal": eating_target} if eating_target else None)
    payload.setdefault("nutrition_view", {"protein_target_g": protein_target})
    return build_bulk_view(payload, goal, today, split=SPLIT, week_starts_on=0)


def titles(v) -> list[str]:
    return [f["title"] for f in v["findings"]]


def finding(v, starts_with: str) -> dict:
    return next(f for f in v["findings"] if f["title"].startswith(starts_with))


# --------------------------------------------------------------- shape / timeline

def test_no_goal_means_no_view():
    assert build_bulk_view({}, None, START) is None


def test_an_empty_payload_still_builds():
    v = view(day(0))
    assert v["weight"] is None
    assert v["intake"]["days_logged"] == 0
    assert v["findings"]


def test_timeline_counts_days_from_the_start():
    v = view(day(9))
    assert v["day_number"] == 10
    assert v["total_days"] == (GOAL.end - GOAL.start).days + 1
    assert v["days_left"] == (GOAL.end - day(9)).days
    assert v["started"] is True and v["finished"] is False


def test_before_the_start_it_reads_as_not_started():
    v = view(START - timedelta(days=3))
    assert v["started"] is False
    assert v["day_number"] == 0


def test_after_the_end_the_day_count_stops():
    v = view(GOAL.end + timedelta(days=10))
    assert v["finished"] is True
    assert v["day_number"] == v["total_days"]
    assert v["days_left"] == 0


# --------------------------------------------------------------- weight

def test_without_a_weigh_in_since_the_start_the_baseline_is_flagged_stale():
    before = {"date": (START - timedelta(days=37)).isoformat(), "weight_kg": 94.45, "body_fat_pct": 19.1}
    v = view(day(1), body_comp=[before])
    assert v["weight"]["baseline_is_stale"] is True
    assert v["weight"]["start_kg"] == 94.45
    assert finding(v, "No weigh-in since the bulk started")["severity"] == "warn"


def test_the_first_weigh_in_of_the_bulk_becomes_the_start_line():
    before = {"date": (START - timedelta(days=37)).isoformat(), "weight_kg": 94.45}
    v = view(day(3), body_comp=[before, scan(1, 95.8), scan(3, 96.1)])
    w = v["weight"]
    assert w["baseline_is_stale"] is False
    assert w["start_kg"] == 95.8
    assert w["current_kg"] == 96.1
    assert w["gained_kg"] == 0.3
    assert w["target_kg"] == 100.8
    assert w["readings_since_start"] == 2


def test_weigh_ins_dated_after_today_are_ignored():
    v = view(day(2), body_comp=[scan(1, 95.0), scan(30, 99.0)])
    assert v["weight"]["current_kg"] == 95.0


def test_no_rate_is_read_off_weigh_ins_days_apart():
    v = view(day(5), body_comp=[scan(1, 95.0), scan(5, 96.2)])
    assert v["weight"]["rate_kg_per_week"] is None
    assert finding(v, "Too early to read a gain rate")["severity"] == "info"


def test_a_rate_inside_the_band_is_on_plan():
    # +0.7kg across 14 days is 0.35 kg a week.
    v = view(day(60), body_comp=[scan(40, 97.0), scan(54, 97.7)])
    assert v["weight"]["rate_kg_per_week"] == 0.35
    assert finding(v, "Gaining +0.35 kg a week")["severity"] == "good"


def test_the_rate_is_a_fitted_slope_so_one_heavy_morning_does_not_set_it():
    # A steady 0.35 kg/week with one water-heavy reading on the last day.
    steady = [scan(40, 97.0), scan(47, 97.35), scan(54, 97.7), scan(61, 98.05)]
    spiked = steady[:-1] + [scan(61, 99.5)]
    endpoint_rate = (99.5 - 97.0) / 21 * 7
    v = view(day(61), body_comp=spiked)
    assert v["weight"]["rate_kg_per_week"] < endpoint_rate


def test_gaining_too_fast_is_a_warning_once_creatine_has_loaded():
    v = view(day(60), body_comp=[scan(40, 97.0), scan(54, 99.0)])  # 1.0 kg/week
    f = finding(v, "Gaining too fast")
    assert f["severity"] == "warn"
    assert "150 kcal" in f["detail"]


def test_a_fast_start_is_not_a_warning_while_creatine_is_still_loading():
    v = view(day(10), body_comp=[scan(1, 95.0), scan(10, 96.6)])
    f = finding(v, "Up +")
    assert f["severity"] == "info"
    assert "creatine" in f["title"]
    assert not any(t.startswith("Gaining too fast") for t in titles(v))


def test_a_flat_scale_is_only_called_a_stall_after_two_weeks():
    early = view(day(9), goal=BulkGoal(start=START, end=GOAL.end), body_comp=[scan(1, 95.0), scan(9, 95.0)])
    assert finding(early, "Gain rate")["severity"] == "info"
    late = view(day(20), goal=BulkGoal(start=START, end=GOAL.end), body_comp=[scan(1, 95.0), scan(20, 95.1)])
    assert finding(late, "Not gaining")["severity"] == "warn"


def test_lean_and_fat_change_are_split_from_body_fat_readings():
    v = view(day(60), body_comp=[scan(40, 96.0, 19.0), scan(54, 97.0, 19.0)])
    w = v["weight"]
    assert w["fat_change_kg"] == 0.19
    assert w["lean_change_kg"] == 0.81


def test_gain_that_is_mostly_fat_is_flagged():
    v = view(day(60), body_comp=[scan(40, 96.0, 19.0), scan(54, 97.5, 20.2)])
    assert "More fat than lean mass so far" in titles(v)


def test_body_fat_past_the_ceiling_is_flagged():
    v = view(day(60), body_comp=[scan(40, 99.0, 21.0), scan(54, 99.5, 21.6)])
    assert finding(v, "Body fat at 21.6%")["severity"] == "warn"


# --------------------------------------------------------------- intake

def test_intake_averages_complete_days_and_leaves_today_out():
    today = day(10)
    log = [food(today, 900)] + [food(today - timedelta(days=i), 3000) for i in (1, 2, 3)]
    v = view(today, nutrition=log)
    i = v["intake"]
    assert i["days_logged"] == 3
    assert i["avg_kcal"] == 3000
    assert i["gap_kcal"] == -100
    assert i["days_on_target"] == 3  # 3000 is within 5% of 3100
    assert "Intake is on the target" in titles(v)


def test_under_eating_is_called_out_with_the_numbers():
    today = day(10)
    v = view(today, nutrition=[food(today - timedelta(days=i), 2500) for i in (1, 2, 3, 4)])
    f = finding(v, "Under-eating by 600 kcal a day")
    assert f["severity"] == "warn"
    assert v["intake"]["days_on_target"] == 0


def test_two_logged_days_are_too_few_for_an_intake_verdict():
    today = day(10)
    v = view(today, nutrition=[food(today - timedelta(days=i), 2000) for i in (1, 2)])
    assert not any(t.startswith("Under-eating") for t in titles(v))


def test_a_food_log_gone_quiet_is_the_finding():
    today = day(10)
    v = view(today, nutrition=[food(today - timedelta(days=6), 3100)])
    assert finding(v, "The food log is empty")["severity"] == "warn"
    assert v["intake"]["days_since_logged"] == 6


def test_low_protein_is_flagged_even_when_calories_are_right():
    today = day(10)
    v = view(today, nutrition=[food(today - timedelta(days=i), 3100, protein=120) for i in (1, 2, 3)])
    assert finding(v, "Protein short: 120g of 190g")["severity"] == "warn"


def test_the_intake_chart_series_marks_unlogged_days_as_gaps():
    today = day(20)
    v = view(today, nutrition=[food(today - timedelta(days=2), 3000)])
    series = v["intake"]["series"]
    assert len(series) == 14
    assert series[-1]["date"] == today.isoformat() and series[-1]["kcal"] is None
    assert series[-3]["kcal"] == 3000


def test_intake_still_reports_without_an_eating_target():
    today = day(10)
    v = view(today, eating_target=None, nutrition=[food(today - timedelta(days=i), 3000) for i in (1, 2, 3)])
    assert v["intake"]["avg_kcal"] == 3000
    assert v["intake"]["gap_kcal"] is None
    assert v["intake"]["days_on_target"] is None


# --------------------------------------------------------------- creatine

def test_creatine_counts_days_from_its_own_start():
    v = view(date(2026, 10, 12))
    c = v["creatine"]
    assert c["day"] == 7
    assert c["pct"] == 25
    assert c["saturated"] is False
    assert c["saturated_on"] == "2026-11-02"


def test_a_missed_creatine_day_pushes_saturation_back():
    lifestyle = [{"date": "2026-10-09", "creatine": False}, {"date": "2026-10-10", "creatine": True}]
    c = view(date(2026, 10, 12), lifestyle=lifestyle)["creatine"]
    assert c["days_missed"] == 1
    assert c["days_taken"] == 6
    assert c["saturated_on"] == "2026-11-03"


def test_creatine_reads_as_loaded_after_four_weeks():
    c = view(date(2026, 11, 10))["creatine"]
    assert c["saturated"] is True and c["pct"] == 100


def test_no_creatine_block_when_it_is_not_being_taken():
    assert view(day(5), goal=BulkGoal(start=START, end=GOAL.end))["creatine"] is None


# --------------------------------------------------------------- lifting

def gym(d: date) -> dict:
    return {"date": d.isoformat(), "type": "gym"}


def test_the_week_plan_comes_from_the_split():
    v = view(date(2026, 10, 14))  # a Wednesday
    lifting = v["lifting"]
    assert lifting["planned"] == 5
    assert [d["weekday"] for d in lifting["days"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert [d["lift"] for d in lifting["days"]] == [True, True, True, False, True, True, False]
    assert lifting["days"][2]["is_today"] is True
    assert lifting["days"][2]["name"] == "Arms & Shoulders"


def test_only_gym_sessions_this_week_count_as_done():
    wednesday = date(2026, 10, 14)
    sessions = [
        gym(date(2026, 10, 12)),                              # Monday, this week
        {"date": "2026-10-13", "type": "padel"},              # not lifting
        gym(date(2026, 10, 10)),                              # last week
    ]
    lifting = view(wednesday, training={"sessions": sessions})["lifting"]
    assert lifting["done"] == 1
    assert lifting["missed"] == 1  # Tuesday's pull day
    assert "1 planned lifting day(s) missed this week" in titles(view(wednesday, training={"sessions": sessions}))


def test_today_is_never_counted_as_missed():
    monday = date(2026, 10, 12)
    assert view(monday)["lifting"]["missed"] == 0


# --------------------------------------------------------------- eating target

def burn_days(today: date, kcal: float, n: int = 10) -> list[dict]:
    return [
        {"date": (today - timedelta(days=i)).isoformat(), "total_kcal": kcal, "bmr_kcal": 2000, "active_kcal": kcal - 2000}
        for i in range(1, n + 1)
    ]


def test_eating_target_needs_a_bulk_and_a_burn_history():
    today = day(5)
    assert build_eating_target({"calorie_trend": burn_days(today, 2800)}, today, None) is None
    assert build_eating_target({}, today, GOAL) is None


def test_eating_target_is_the_trailing_burn_plus_the_surplus():
    today = day(5)
    payload = {
        "calorie_trend": burn_days(today, 2830),
        "nutrition_view": {"today_intake_kcal": 1200, "today_protein_g": 80, "protein_target_g": 190},
    }
    t = build_eating_target(payload, today, GOAL)
    assert t["benchmark_kcal"] == 2830
    assert t["daily_target_kcal"] == 3150  # 2830 + 300, to the nearest 50
    assert t["remaining_kcal"] == 1950
    assert t["protein_remaining_g"] == 110
    assert t["hit"] is False and t["over"] is False


def test_today_is_left_out_of_the_burn_benchmark():
    today = day(5)
    trend = burn_days(today, 2800) + [{"date": today.isoformat(), "total_kcal": 900, "bmr_kcal": 900, "active_kcal": 0}]
    assert build_eating_target({"calorie_trend": trend}, today, GOAL)["benchmark_kcal"] == 2800


def test_eating_target_reads_hit_from_ninety_five_percent():
    today = day(5)
    payload = {"calorie_trend": burn_days(today, 2800), "nutrition_view": {"today_intake_kcal": 2950}}
    t = build_eating_target(payload, today, GOAL)
    assert t["daily_target_kcal"] == 3100
    assert t["hit"] is True and t["rank"] == "good"


def test_eating_well_past_the_target_is_flagged_as_over():
    today = day(5)
    payload = {"calorie_trend": burn_days(today, 2800), "nutrition_view": {"today_intake_kcal": 3600}}
    t = build_eating_target(payload, today, GOAL)
    assert t["over"] is True and t["rank"] == "fair"
    assert t["remaining_kcal"] == -500
