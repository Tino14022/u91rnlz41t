"""The landing view: latest state of every domain, and what needs attention.

Deliberately a summary and not a second copy of the app. Each card carries the
most recent fact from its domain, how old that fact is, and a link to the tab
holding the detail. Age is part of the point — a nutrition card reading "last
logged 6 days ago" tells you something no amount of detail on the Nutrition tab
can, because the tab can only show what was logged.
"""
from __future__ import annotations

from datetime import date

from . import rank as rank_scale
from .formatting import parse_iso

# Past this many days a domain is treated as not being kept up, and says so.
STALE_AFTER = {
    "sleep": 2,
    "training": 4,
    "running": 7,
    "nutrition": 2,
    "body": 10,
}


def _age(iso_date: str | None, today: date) -> int | None:
    d = parse_iso(iso_date) if iso_date else None
    return (today - d).days if d else None


def _ago(days: int | None) -> str:
    if days is None:
        return "never"
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _card(domain, icon, title, value, unit=None, sub=None, status="info", age=None, tab=None):
    stale = age is not None and age > STALE_AFTER.get(domain, 99)
    final_status = "warn" if stale else status
    return {
        "domain": domain,
        "icon": icon,
        "title": title,
        "value": value,
        "unit": unit,
        "sub": sub,
        "status": final_status,
        "rank": rank_scale.from_severity(final_status),
        "age_days": age,
        "age_label": _ago(age),
        "stale": stale,
        "tab": tab or domain,
    }


def _sleep_card(payload, today):
    nights = [n for n in payload.get("sleep_trend") or [] if n.get("date")]
    if not nights:
        return _card("sleep", "😴", "Sleep", "—", sub="nothing recorded", status="info")
    last = max(nights, key=lambda n: n["date"])
    score = last.get("score")
    hours = last.get("hours")
    status = "good" if (score or 0) >= 80 else "warn" if (score or 0) < 65 else "info"
    return _card(
        "sleep", "😴", "Last night", score if score is not None else "—", "score",
        sub=(f"{hours}h" if hours else "") + (f" · {last.get('quality','').lower()}" if last.get("quality") else ""),
        status=status, age=_age(last["date"], today),
    )


def _training_card(payload, today):
    sessions = (payload.get("training") or {}).get("sessions") or []
    if not sessions:
        return _card("training", "💪", "Training", "—", sub="nothing logged", status="info")
    last = sessions[0]  # already sorted newest first
    streak = (payload.get("training") or {}).get("gamification", {}).get("streak_days", 0)
    label = (last.get("subtype") or last.get("type") or "session").replace("_", " ")
    return _card(
        "training", "💪", "Last session", label.title(), None,
        sub=(f"{last['duration_min']} min" if last.get("duration_min") else "logged")
            + (f" · {streak} day streak" if streak else ""),
        status="good", age=_age(last.get("date"), today),
    )


def _running_card(payload, today):
    # A lifting block with no race booked has no running to keep up with, and
    # a card that only ever says "last run 40 days ago" is noise.
    if payload.get("bulk") and not payload.get("race"):
        return None
    runs = payload.get("recent_runs") or []
    plan = payload.get("race_plan") or {}
    if not runs:
        return _card("running", "🏃", "Running", "—", sub="no runs recorded", status="info")
    last = runs[0]
    sub = last.get("pace_label", "")
    if plan.get("next_long_run_km"):
        sub += f" · next long run {plan['next_long_run_km']}km"
    return _card(
        "running", "🏃", "Last run", last.get("distance_km"), "km",
        sub=sub, status="good", age=_age(last.get("date"), today),
    )


def _nutrition_card(payload, today):
    nv = payload.get("nutrition_view") or {}
    entries = [n for n in payload.get("nutrition") or [] if n.get("date")]
    if not entries:
        return _card("nutrition", "🍽️", "Nutrition", "—", sub="nothing logged", status="info")
    last_date = max(n["date"] for n in entries)
    logged = sum(n.get("calories") or 0 for n in entries if n["date"] == last_date)
    protein = sum(n.get("protein_g") or 0 for n in entries if n["date"] == last_date)
    target = nv.get("protein_target_g")
    sub = f"{round(protein)}g protein" + (f" / {target}g" if target else "")
    return _card(
        "nutrition", "🍽️", "Last logged day", round(logged), "kcal",
        sub=sub, status="info", age=_age(last_date, today),
    )


def _body_card(payload, today):
    bv = payload.get("body_view")
    if not bv:
        return _card("body", "⚖️", "Body", "—", sub="no weigh-in yet", status="info")
    latest = bv["latest"]
    return _card(
        "body", "⚖️", "Latest weigh-in", latest.get("weight_kg"), "kg",
        sub=f"{latest.get('body_fat_pct')}% body fat · {bv.get('fat_mass_kg')}kg fat",
        status="info", age=_age(bv.get("measured_on"), today),
    )


def _recovery_card(payload, today):
    scores = (payload.get("training") or {}).get("muscle_scores") or {}
    if not scores:
        return _card("recovery", "🩹", "Recovery", "All clear", sub="nothing sore", status="good", tab="training")
    sore = sorted(scores.items(), key=lambda kv: -kv[1])
    worst_name, worst_score = sore[0]
    still_sore = [m for m, s in sore if s > 0.45]
    status = "warn" if worst_score > 0.7 else "info" if worst_score > 0.45 else "good"
    return _card(
        "recovery", "🩹", "Least recovered", worst_name.replace("_", " ").title(), None,
        sub=(f"{len(still_sore)} groups still recovering" if still_sore else "everything close to fresh"),
        status=status, tab="training",
    )


def _race_card(payload, today):
    race = payload.get("race") or {}
    plan = payload.get("race_plan") or {}
    if not race:
        return None
    days = race.get("days_remaining")
    status = "info"
    sub = race.get("name", "")
    if plan:
        sub = (
            f"longest {plan.get('current_longest_km')}km of {plan.get('race_distance_km')}km"
        )
        status = "good" if plan.get("on_track") else "warn"
    return _card("race", "🏁", "Race day", days, "days", sub=sub, status=status, tab="running")


def _goal_card(payload, today):
    fl = payload.get("fat_loss")
    if not fl:
        return None
    to_lose = fl.get("fat_to_lose_kg")
    if to_lose is not None and to_lose <= 0:
        return _card("goal", "🎯", "Fat loss goal", "Reached", None,
                     sub=f"at or below {fl['target_body_fat_pct']}%", status="good", tab="body")
    return _card(
        "goal", "🎯", "Fat to lose", to_lose, "kg",
        sub=f"{fl.get('current_body_fat_pct')}% → {fl.get('target_body_fat_pct')}% · "
            f"{fl.get('required_daily_deficit_kcal')} kcal/day",
        status="info", tab="body",
    )


def _bulk_card(payload, today):
    bulk = payload.get("bulk")
    if not bulk:
        return None
    weight = bulk.get("weight")
    sub = f"day {bulk['day_number']} of {bulk['total_days']}"
    if not weight or weight.get("baseline_is_stale"):
        return _card("bulk", "💪", "Bulk", "Weigh in", None,
                     sub=sub + " · no start weight yet", status="warn", tab="bulk")
    rate = weight.get("rate_kg_per_week")
    if rate is not None:
        sub += f" · {rate:+.2f} kg/week"
    status = {"good": "good", "excellent": "good", "fair": "info"}.get(bulk.get("rank"), "warn")
    return _card("bulk", "💪", "Bulk gain", f"{weight['gained_kg']:+.1f}", "kg",
                 sub=sub + f" · target +{weight['target_gain_kg']:g} kg", status=status, tab="bulk")


def _fuel_card(payload, today):
    eating = payload.get("eating_target")
    if not eating:
        return None
    left = eating["remaining_kcal"]
    protein = ""
    if eating.get("protein_target_g"):
        protein = f" · protein {eating['protein_today_g']}/{eating['protein_target_g']}g"
    if left <= 0:
        return _card("fuel", "🍚", "Eating target", "Hit", None,
                     sub=f"{eating['eaten_today_kcal']} of {eating['daily_target_kcal']} kcal" + protein,
                     status="info" if eating.get("over") else "good", tab="nutrition")
    return _card("fuel", "🍚", "Left to eat today", left, "kcal",
                 sub=f"{eating['eaten_today_kcal']} of {eating['daily_target_kcal']} kcal" + protein,
                 status="info", tab="nutrition")


def _money_card(payload, today):
    ev = payload.get("expenses_view")
    if not ev:
        return None
    paycheck = ev.get("paycheck") or {}
    current, upcoming = paycheck.get("current"), paycheck.get("next")
    if current:
        status = {"good": "good", "fair": "info"}.get(current["rank"], "warn")
        return _card("money", "💸", "Left this paycheck", f"{current['remaining_den']:,}", "ден",
                     sub=f"{current['daily_allowance_den']:,} ден a day for {current['days_left']} days",
                     status=status, tab="expenses")
    if ev.get("entry_count"):
        sub = f"{ev['week_total_den']:,} ден this week"
        if upcoming:
            sub += f" · paycheck in {upcoming['days_until']} days"
        return _card("money", "💸", "Spent this month", f"{ev['month_total_den']:,}", "ден",
                     sub=sub, status="info", tab="expenses")
    if upcoming:
        due = parse_iso(upcoming["date"])
        when = f"{due.day} {due:%b}" if due else upcoming["date"]
        return _card("money", "💸", "Next paycheck", upcoming["days_until"], "days",
                     sub=f"{upcoming['amount_den']:,} ден on {when}", status="info", tab="expenses")
    return None


CARD_BUILDERS = [
    _race_card,
    _bulk_card,
    _fuel_card,
    _goal_card,
    _sleep_card,
    _training_card,
    _recovery_card,
    _running_card,
    _nutrition_card,
    _body_card,
    _money_card,
]


def build_overview(payload: dict, today: date) -> dict:
    cards = []
    for build in CARD_BUILDERS:
        try:
            card = build(payload, today)
        except Exception as e:  # noqa: BLE001 - one bad card must not kill the page
            print(f"  ! overview card {build.__name__} failed: {e}")
            continue
        if card:
            cards.append(card)

    # What to do something about, worst first, capped so it stays a summary.
    priorities: list[dict] = []
    health = payload.get("build_health") or {}
    if not health.get("healthy", True):
        names = ", ".join(f["name"].replace("_", " ") for f in health.get("failures", []))
        priorities.append({
            "severity": "warn",
            "title": "Some Garmin data is missing",
            "detail": f"This build couldn't fetch: {names}. Charts using it are incomplete.",
            "tab": None,
        })
    for f in (payload.get("insights") or {}).get("findings", []):
        if f["severity"] == "warn":
            priorities.append({
                "severity": "warn",
                "title": f["headline"],
                "detail": f["detail"],
                "confidence": f.get("confidence"),
                "tab": "analysis",
            })
    for f in (payload.get("bulk") or {}).get("findings", []):
        if f["severity"] == "warn":
            priorities.append({**f, "tab": "bulk"})
    for f in (payload.get("fat_loss") or {}).get("findings", []):
        if f["severity"] == "warn":
            priorities.append({**f, "tab": "body"})
    for f in (payload.get("body_view") or {}).get("findings", []):
        if f["severity"] == "warn":
            priorities.append({**f, "tab": "body"})

    for p in priorities:
        p["rank"] = rank_scale.from_severity(p.get("severity"))
    stale = [c for c in cards if c["stale"]]

    return {
        "cards": cards,
        "priorities": priorities[:5],
        "priority_count": len(priorities),
        "stale_domains": [c["domain"] for c in stale],
        "workout_plan": payload.get("workout_plan"),
        "today": {
            "intake_kcal": (payload.get("nutrition_view") or {}).get("today_intake_kcal"),
            "protein_g": (payload.get("nutrition_view") or {}).get("today_protein_g"),
            "burn_kcal": (payload.get("nutrition_view") or {}).get("today_burn_so_far_kcal"),
            "protein_target_g": (payload.get("nutrition_view") or {}).get("protein_target_g"),
            "kcal_target": (payload.get("eating_target") or {}).get("daily_target_kcal"),
        },
    }
