"""The overview: latest state per domain, staleness, and what needs attention."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.domain.overview import build_overview

TODAY = date(2026, 8, 15)


def iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def cards_by_domain(payload):
    return {c["domain"]: c for c in build_overview(payload, TODAY)["cards"]}


BULK = {
    "day_number": 12, "total_days": 141, "rank": "good", "findings": [],
    "weight": {"baseline_is_stale": False, "gained_kg": 0.6, "target_gain_kg": 5.0, "rate_kg_per_week": 0.35},
}
EATING = {
    "remaining_kcal": 1400, "eaten_today_kcal": 1700, "daily_target_kcal": 3100, "over": False,
    "protein_today_g": 90, "protein_target_g": 190,
}


def test_empty_payload_still_produces_a_page():
    ov = build_overview({}, TODAY)
    assert ov["cards"]
    assert ov["priorities"] == []
    assert all(c["value"] in ("—", "All clear") for c in ov["cards"])


def test_each_domain_reports_its_most_recent_entry():
    payload = {
        "sleep_trend": [
            {"date": iso(3), "score": 60, "hours": 6.0},
            {"date": iso(1), "score": 84, "hours": 7.4, "quality": "GOOD"},
        ],
        "training": {"sessions": [
            {"date": iso(1), "type": "gym", "subtype": "push", "duration_min": 65},
            {"date": iso(4), "type": "gym", "subtype": "legs", "duration_min": 70},
        ], "gamification": {"streak_days": 3}},
        "recent_runs": [{"date": iso(2), "distance_km": 7.05, "pace_label": "6:25/km"}],
        "nutrition": [{"date": iso(1), "calories": 2400, "protein_g": 180}],
        "nutrition_view": {"protein_target_g": 198},
        "body_view": {"latest": {"weight_kg": 98.9, "body_fat_pct": 20.3}, "measured_on": iso(0), "fat_mass_kg": 20.1},
    }
    c = cards_by_domain(payload)
    assert c["sleep"]["value"] == 84            # newest night, not the older one
    assert c["training"]["value"] == "Push"     # newest session
    assert c["running"]["value"] == 7.05
    assert c["nutrition"]["value"] == 2400
    assert c["body"]["value"] == 98.9


def test_age_is_reported_in_plain_language():
    payload = {"sleep_trend": [{"date": iso(0), "score": 80}]}
    assert cards_by_domain(payload)["sleep"]["age_label"] == "today"
    payload = {"sleep_trend": [{"date": iso(1), "score": 80}]}
    assert cards_by_domain(payload)["sleep"]["age_label"] == "yesterday"
    payload = {"sleep_trend": [{"date": iso(5), "score": 80}]}
    assert cards_by_domain(payload)["sleep"]["age_label"] == "5 days ago"


def test_a_domain_that_has_stopped_being_updated_is_flagged():
    """The thing an overview can say that no single tab can."""
    payload = {"nutrition": [{"date": iso(6), "calories": 2400, "protein_g": 180}]}
    ov = build_overview(payload, TODAY)
    card = next(c for c in ov["cards"] if c["domain"] == "nutrition")
    assert card["stale"] is True
    assert card["status"] == "warn"
    assert "nutrition" in ov["stale_domains"]


def test_a_freshly_updated_domain_is_not_flagged():
    payload = {"nutrition": [{"date": iso(1), "calories": 2400, "protein_g": 180}]}
    ov = build_overview(payload, TODAY)
    assert ov["stale_domains"] == []


def test_domains_have_their_own_staleness_thresholds():
    """A weigh-in 6 days old is fine; a food log 6 days old is not."""
    body = {"body_view": {"latest": {"weight_kg": 98.9, "body_fat_pct": 20.3}, "measured_on": iso(6), "fat_mass_kg": 20.1}}
    assert build_overview(body, TODAY)["stale_domains"] == []
    food = {"nutrition": [{"date": iso(6), "calories": 2400}]}
    assert build_overview(food, TODAY)["stale_domains"] == ["nutrition"]


def test_sleep_status_reflects_the_score():
    assert cards_by_domain({"sleep_trend": [{"date": iso(0), "score": 85}]})["sleep"]["status"] == "good"
    assert cards_by_domain({"sleep_trend": [{"date": iso(0), "score": 55}]})["sleep"]["status"] == "warn"
    assert cards_by_domain({"sleep_trend": [{"date": iso(0), "score": 72}]})["sleep"]["status"] == "info"


def test_recovery_card_names_the_least_recovered_group():
    payload = {"training": {"muscle_scores": {"chest": 0.92, "quads": 0.5, "lats": 0.1}}}
    card = cards_by_domain(payload)["recovery"]
    assert card["value"] == "Chest"
    assert card["status"] == "warn"
    assert "2 groups still recovering" in card["sub"]


def test_recovery_card_when_nothing_is_sore():
    card = cards_by_domain({"training": {"muscle_scores": {}}})["recovery"]
    assert card["value"] == "All clear"
    assert card["status"] == "good"


def test_race_card_reflects_whether_the_plan_is_on_track():
    behind = {
        "race": {"days_remaining": 50, "name": "Half"},
        "race_plan": {"on_track": False, "current_longest_km": 7.05, "race_distance_km": 21.1},
    }
    assert cards_by_domain(behind)["race"]["status"] == "warn"
    ahead = {**behind, "race_plan": {**behind["race_plan"], "on_track": True}}
    assert cards_by_domain(ahead)["race"]["status"] == "good"


def test_goal_card_disappears_without_a_goal():
    assert "goal" not in cards_by_domain({})
    with_goal = {"fat_loss": {"fat_to_lose_kg": 2.8, "current_body_fat_pct": 20.3,
                              "target_body_fat_pct": 18.0, "required_daily_deficit_kcal": 440}}
    assert cards_by_domain(with_goal)["goal"]["value"] == 2.8


def test_goal_card_reports_a_reached_target():
    reached = {"fat_loss": {"fat_to_lose_kg": -0.4, "target_body_fat_pct": 18.0}}
    card = cards_by_domain(reached)["goal"]
    assert card["value"] == "Reached"
    assert card["status"] == "good"


def test_priorities_gather_warnings_from_every_source():
    payload = {
        "build_health": {"healthy": False, "failures": [{"name": "sleep_trend", "error": "401"}]},
        "insights": {"findings": [
            {"severity": "warn", "headline": "Bedtime swings", "detail": "...", "confidence": "solid"},
            {"severity": "good", "headline": "Fine", "detail": "..."},
        ]},
        "fat_loss": {"findings": [{"severity": "warn", "title": "Lean mass down", "detail": "..."}]},
        "body_view": {"findings": [{"severity": "warn", "title": "Water low", "detail": "..."}]},
    }
    ov = build_overview(payload, TODAY)
    titles = [p["title"] for p in ov["priorities"]]
    assert "Some Garmin data is missing" in titles
    assert "Bedtime swings" in titles
    assert "Lean mass down" in titles
    assert "Water low" in titles
    assert "Fine" not in titles       # good news is not a priority
    assert ov["priority_count"] == 4


def test_priorities_are_capped_but_the_true_count_is_kept():
    payload = {"insights": {"findings": [
        {"severity": "warn", "headline": f"Issue {i}", "detail": "..."} for i in range(9)
    ]}}
    ov = build_overview(payload, TODAY)
    assert len(ov["priorities"]) == 5
    assert ov["priority_count"] == 9


def test_today_block_carries_the_in_progress_numbers():
    payload = {"nutrition_view": {
        "today_intake_kcal": 820, "today_protein_g": 55,
        "today_burn_so_far_kcal": 1035, "protein_target_g": 198,
    }}
    assert build_overview(payload, TODAY)["today"] == {
        "intake_kcal": 820, "protein_g": 55, "burn_kcal": 1035, "protein_target_g": 198,
        "kcal_target": None,
    }


def test_every_card_links_to_a_real_tab():
    payload = {
        "training": {"muscle_scores": {"chest": 0.9}},
        "fat_loss": {"fat_to_lose_kg": 2.0},
        "bulk": BULK,
        "eating_target": EATING,
        "expenses_view": {"entry_count": 3, "week_total_den": 900, "month_total_den": 4200, "paycheck": None},
    }
    tabs = {"overview", "bulk", "analysis", "workout", "training", "running", "sleep", "nutrition", "body", "expenses"}
    for card in build_overview(payload, TODAY)["cards"]:
        assert card["tab"] in tabs, f"{card['domain']} links to unknown tab {card['tab']}"


def test_a_failing_card_cannot_take_down_the_page(monkeypatch):
    from garmin_dashboard.domain import overview

    def explode(payload, today):
        raise ValueError("boom")

    monkeypatch.setattr(overview, "CARD_BUILDERS", [explode, overview._sleep_card])
    ov = overview.build_overview({"sleep_trend": [{"date": iso(0), "score": 80}]}, TODAY)
    assert len(ov["cards"]) == 1


# --------------------------------------------------------------- bulk mode

def test_bulk_card_leads_with_the_gain_and_links_to_the_bulk_tab():
    card = cards_by_domain({"bulk": BULK})["bulk"]
    assert card["value"] == "+0.6" and card["unit"] == "kg"
    assert "day 12 of 141" in card["sub"] and "+0.35 kg/week" in card["sub"]
    assert card["tab"] == "bulk" and card["status"] == "good"


def test_bulk_card_asks_for_a_weigh_in_until_there_is_a_start_weight():
    stale = {**BULK, "weight": {"baseline_is_stale": True, "gained_kg": 0, "target_gain_kg": 5.0}}
    for bulk in (stale, {**BULK, "weight": None}):
        card = cards_by_domain({"bulk": bulk})["bulk"]
        assert card["value"] == "Weigh in"
        assert card["status"] == "warn"


def test_fuel_card_shows_what_is_left_to_eat():
    card = cards_by_domain({"eating_target": EATING})["fuel"]
    assert card["value"] == 1400 and card["unit"] == "kcal"
    assert "1700 of 3100 kcal" in card["sub"] and "protein 90/190g" in card["sub"]
    assert card["tab"] == "nutrition"


def test_fuel_card_reads_hit_once_the_target_is_eaten():
    card = cards_by_domain({"eating_target": {**EATING, "remaining_kcal": -50, "eaten_today_kcal": 3150}})["fuel"]
    assert card["value"] == "Hit" and card["status"] == "good"


def test_running_card_is_dropped_in_a_bulk_with_no_race():
    runs = {"recent_runs": [{"date": iso(40), "distance_km": 21.2, "pace_label": "5:51/km"}]}
    assert "running" not in cards_by_domain({**runs, "bulk": BULK})
    assert "running" in cards_by_domain({**runs, "bulk": BULK, "race": {"name": "Spring Half", "days_remaining": 90}})
    assert "running" in cards_by_domain(runs)


def test_money_card_follows_the_paycheck_state():
    current = {"remaining_den": 40000, "daily_allowance_den": 2500, "days_left": 16, "rank": "good"}
    upcoming = {"date": "2026-11-04", "amount_den": 55500, "days_until": 23}

    running_balance = cards_by_domain({"expenses_view": {"entry_count": 4, "paycheck": {"current": current, "next": None}}})["money"]
    assert running_balance["value"] == "40,000" and running_balance["tab"] == "expenses"
    assert "2,500 ден a day for 16 days" in running_balance["sub"]

    spending = cards_by_domain({"expenses_view": {
        "entry_count": 2, "week_total_den": 900, "month_total_den": 4200,
        "paycheck": {"current": None, "next": upcoming},
    }})["money"]
    assert spending["value"] == "4,200" and "paycheck in 23 days" in spending["sub"]

    countdown = cards_by_domain({"expenses_view": {"entry_count": 0, "paycheck": {"current": None, "next": upcoming}}})["money"]
    assert countdown["value"] == 23 and countdown["unit"] == "days"

    assert "money" not in cards_by_domain({})


def test_bulk_warnings_surface_as_priorities_pointing_at_the_bulk_tab():
    bulk = {**BULK, "findings": [
        {"severity": "warn", "title": "The food log is empty", "detail": "...", "rank": "bad"},
        {"severity": "good", "title": "Gaining on plan", "detail": "...", "rank": "good"},
    ]}
    priorities = build_overview({"bulk": bulk}, TODAY)["priorities"]
    assert [(p["title"], p["tab"]) for p in priorities] == [("The food log is empty", "bulk")]
