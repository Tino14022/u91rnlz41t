"""The bulk: how far in, whether weight is arriving at the right speed, whether
enough is being eaten, where creatine loading stands, and the week's lifting.

A bulk fails in two quiet ways — not eating enough to grow, or eating so much
that most of the gain is fat. Both show up in the same two numbers (intake
against target, weekly gain against a band), so those lead and everything else
supports them.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import rank as rank_scale
from .formatting import iso, parse_iso, week_start
from .fuelling import TARGET_HIT_RATIO

# A gain rate read off two weigh-ins a couple of days apart is water and
# breakfast, not tissue.
MIN_DAYS_FOR_RATE = 7
# How long the scale is given before "not gaining" becomes a finding.
MIN_DAYS_FOR_STALL = 14
# Creatine pulls roughly this much water into muscle as it saturates.
CREATINE_WATER_KG = (1.0, 2.0)
INTAKE_WINDOW_DAYS = 7
INTAKE_CHART_DAYS = 14
# Fewer logged days than this and a weekly intake average says nothing.
MIN_LOGGED_DAYS = 3
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _finding(severity: str, title: str, detail: str) -> dict:
    return {
        "severity": severity,
        "title": title,
        "detail": detail,
        "rank": rank_scale.from_severity(severity),
    }


def _short_date(iso_date: str) -> str:
    d = parse_iso(iso_date)
    return f"{d.day} {d:%b}" if d else iso_date


def _readings(body_comp: list[dict]) -> list[dict]:
    rows = []
    for b in body_comp or []:
        d = parse_iso(b.get("date"))
        if d is None or not b.get("weight_kg"):
            continue
        rows.append({"day": d, **b})
    return sorted(rows, key=lambda r: r["day"])


def _split(reading: dict) -> tuple[float, float] | None:
    """(fat_kg, lean_kg) for a reading, or None if it carries no body fat."""
    bf = reading.get("body_fat_pct")
    if bf is None:
        return None
    fat = reading["weight_kg"] * bf / 100
    return fat, reading["weight_kg"] - fat


def _weekly_rate(since: list[dict]) -> float | None:
    """kg per week across the readings taken since the bulk began."""
    if len(since) < 2:
        return None
    span = (since[-1]["day"] - since[0]["day"]).days
    if span < MIN_DAYS_FOR_RATE:
        return None
    if len(since) >= 3:
        # A fitted slope rather than last-minus-first, so one salty dinner
        # before a weigh-in does not set the whole rate.
        xs = [(r["day"] - since[0]["day"]).days for r in since]
        ys = [r["weight_kg"] for r in since]
        mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator:
            slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
            return slope * 7
    return (since[-1]["weight_kg"] - since[0]["weight_kg"]) / span * 7


def _weight(body_comp: list[dict], goal, today: date) -> dict | None:
    readings = _readings(body_comp)
    if not readings:
        return None
    since = [r for r in readings if goal.start <= r["day"] <= today]
    before = [r for r in readings if r["day"] < goal.start]
    if not since and not before:
        return None
    baseline = since[0] if since else before[-1]
    current = since[-1] if since else baseline

    start_kg = baseline["weight_kg"]
    target_kg = round(start_kg + goal.target_gain_kg, 1)
    gained = round(current["weight_kg"] - start_kg, 2)
    rate = _weekly_rate(since)

    out = {
        "start_kg": start_kg,
        "start_date": iso(baseline["day"]),
        # True until a weigh-in lands inside the bulk: the start line is then
        # an older reading standing in for one.
        "baseline_is_stale": not since,
        "current_kg": current["weight_kg"],
        "current_date": iso(current["day"]),
        "current_body_fat_pct": current.get("body_fat_pct"),
        "target_kg": target_kg,
        "target_gain_kg": goal.target_gain_kg,
        "gained_kg": gained,
        "to_go_kg": round(target_kg - current["weight_kg"], 2),
        "pct": round(max(0.0, min(1.0, gained / goal.target_gain_kg)) * 100)
        if goal.target_gain_kg
        else None,
        "readings_since_start": len(since),
        "rate_kg_per_week": round(rate, 2) if rate is not None else None,
        "rate_min_kg": goal.weekly_gain_min_kg,
        "rate_max_kg": goal.weekly_gain_max_kg,
        "lean_change_kg": None,
        "fat_change_kg": None,
    }
    first, last = _split(baseline), _split(current)
    if since and len(since) >= 2 and first and last:
        out["fat_change_kg"] = round(last[0] - first[0], 2)
        out["lean_change_kg"] = round(last[1] - first[1], 2)
    return out


def _intake(nutrition: list[dict], today: date, target_kcal, protein_target) -> dict:
    by_day: dict[str, dict] = {}
    for n in nutrition or []:
        d = n.get("date")
        if not parse_iso(d):
            continue
        day = by_day.setdefault(d, {"kcal": 0.0, "protein": 0.0})
        day["kcal"] += n.get("calories") or 0
        day["protein"] += n.get("protein_g") or 0

    # Complete days only: today is still being eaten.
    window = [iso(today - timedelta(days=i)) for i in range(1, INTAKE_WINDOW_DAYS + 1)]
    logged = [by_day[d] for d in window if d in by_day]
    avg_kcal = round(statistics.fmean(d["kcal"] for d in logged)) if logged else None
    avg_protein = round(statistics.fmean(d["protein"] for d in logged)) if logged else None

    series = []
    for i in range(INTAKE_CHART_DAYS - 1, -1, -1):
        d = iso(today - timedelta(days=i))
        day = by_day.get(d)
        series.append({
            "date": d,
            "kcal": round(day["kcal"]) if day else None,
            "protein_g": round(day["protein"]) if day else None,
        })

    last_logged = max(by_day) if by_day else None
    return {
        "window_days": INTAKE_WINDOW_DAYS,
        "days_logged": len(logged),
        "avg_kcal": avg_kcal,
        "avg_protein_g": avg_protein,
        "target_kcal": target_kcal,
        "protein_target_g": protein_target,
        "gap_kcal": (avg_kcal - target_kcal) if (avg_kcal is not None and target_kcal) else None,
        "days_on_target": sum(1 for d in logged if d["kcal"] >= target_kcal * TARGET_HIT_RATIO)
        if target_kcal
        else None,
        "days_protein_hit": sum(1 for d in logged if d["protein"] >= protein_target * 0.9)
        if protein_target
        else None,
        "last_logged": last_logged,
        "days_since_logged": (today - parse_iso(last_logged)).days if last_logged else None,
        "series": series,
    }


def _creatine(goal, lifestyle: list[dict], today: date) -> dict | None:
    if goal.creatine_start is None or today < goal.creatine_start:
        return None
    # Taken every day unless a lifestyle entry says otherwise: logging the one
    # missed day is less work than confirming the thirty taken ones.
    missed = {
        d for row in lifestyle or []
        if row.get("creatine") is False
        and (d := parse_iso(row.get("date"))) is not None
        and goal.creatine_start <= d <= today
    }
    days_since_start = (today - goal.creatine_start).days + 1
    days_taken = days_since_start - len(missed)
    saturation_days = goal.creatine_saturation_days
    saturated = days_taken >= saturation_days
    saturated_on = goal.creatine_start + timedelta(days=saturation_days - 1 + len(missed))
    return {
        "start": iso(goal.creatine_start),
        "dose_g": goal.creatine_dose_g,
        "day": days_since_start,
        "days_taken": days_taken,
        "days_missed": len(missed),
        "saturation_days": saturation_days,
        "pct": round(min(1.0, days_taken / saturation_days) * 100),
        "saturated": saturated,
        "saturated_on": iso(saturated_on),
        "water_kg_min": CREATINE_WATER_KG[0],
        "water_kg_max": CREATINE_WATER_KG[1],
    }


def _lifting(training: dict, split: dict, today: date, week_starts_on: int) -> dict | None:
    schedule = (split or {}).get("schedule") or {}
    templates = (split or {}).get("templates") or {}
    if not schedule:
        return None
    wk_start = week_start(today, week_starts_on)
    gym_days = {
        s["date"] for s in (training or {}).get("sessions") or []
        if s.get("type") == "gym" and (d := parse_iso(s.get("date"))) and wk_start <= d <= today
    }
    days = []
    for offset in range(7):
        day = wk_start + timedelta(days=offset)
        slot = schedule.get(str(day.weekday()))
        template = templates.get(slot) or {}
        is_lift = bool(template.get("exercises"))
        days.append({
            "date": iso(day),
            "weekday": WEEKDAY_NAMES[day.weekday()],
            "slot": slot,
            "name": template.get("name") or (slot.replace("_", " ").title() if slot else None),
            "lift": is_lift,
            "done": iso(day) in gym_days,
            "is_today": day == today,
            "past": day < today,
        })
    planned = sum(1 for d in days if d["lift"])
    return {
        "planned": planned,
        "done": len(gym_days),
        "days": days,
        "missed": sum(1 for d in days if d["lift"] and d["past"] and not d["done"]),
    }


def _findings(goal, today, weight, intake, creatine, lifting, day_number) -> list[dict]:
    out: list[dict] = []
    loading = bool(creatine and not creatine["saturated"])

    if weight is None or weight["baseline_is_stale"]:
        measured = f" The last scan on record is from {_short_date(weight['start_date'])}." if weight else ""
        out.append(_finding(
            "warn", "No weigh-in since the bulk started",
            "Everything here is measured from a starting weight, and there isn't one yet." + measured
            + " Step on the scale in the morning so the gain has a start line.",
        ))
    elif weight["rate_kg_per_week"] is None:
        out.append(_finding(
            "info", "Too early to read a gain rate",
            f"A rate needs weigh-ins at least {MIN_DAYS_FOR_RATE} days apart; day-to-day swings are water "
            "and food in transit. Keep weighing in the morning and this turns into a verdict.",
        ))
    else:
        rate = weight["rate_kg_per_week"]
        lo, hi = goal.weekly_gain_min_kg, goal.weekly_gain_max_kg
        if rate > hi:
            if loading:
                out.append(_finding(
                    "info", f"Up {rate:+.2f} kg a week — some of that is creatine water",
                    f"That is above the {lo}–{hi} kg band, but creatine is still loading and pulls "
                    f"{CREATINE_WATER_KG[0]:.0f}–{CREATINE_WATER_KG[1]:.0f} kg of water into muscle over its first "
                    "month. Don't cut food on this number yet; judge the rate once loading is done.",
                ))
            else:
                out.append(_finding(
                    "warn", f"Gaining too fast: {rate:+.2f} kg a week",
                    f"The band is {lo}–{hi} kg a week. Above it the extra is mostly fat, which only buys a longer "
                    "cut in spring. Take about 150 kcal a day off and look again in two weeks.",
                ))
        elif rate < lo:
            if day_number >= MIN_DAYS_FOR_STALL:
                out.append(_finding(
                    "warn", f"Not gaining: {rate:+.2f} kg a week",
                    f"The band is {lo}–{hi} kg a week and the scale isn't moving. The surplus isn't landing — "
                    "add about 150 kcal a day and look again in two weeks.",
                ))
            else:
                out.append(_finding(
                    "info", f"Gain rate {rate:+.2f} kg a week so far",
                    f"Below the {lo}–{hi} kg band, but two weeks is the minimum before changing food on it.",
                ))
        else:
            out.append(_finding(
                "good", f"Gaining {rate:+.2f} kg a week — on plan",
                f"Inside the {lo}–{hi} kg band, which is the speed at which most of the gain can be muscle.",
            ))

    if weight and weight.get("current_body_fat_pct") is not None \
            and weight["current_body_fat_pct"] > goal.max_body_fat_pct:
        out.append(_finding(
            "warn", f"Body fat at {weight['current_body_fat_pct']}% — past the ceiling",
            f"The bulk was set to stop at {goal.max_body_fat_pct}%. From here more surplus mostly adds fat; "
            "hold at maintenance or start the cut.",
        ))
    if weight and weight["lean_change_kg"] is not None and weight["fat_change_kg"] is not None \
            and weight["gained_kg"] >= 1 and weight["fat_change_kg"] > max(0.5, weight["lean_change_kg"]):
        out.append(_finding(
            "warn", "More fat than lean mass so far",
            f"Since the start the scale reads {weight['fat_change_kg']:+.1f} kg fat against "
            f"{weight['lean_change_kg']:+.1f} kg lean. Scale body-fat readings are noisy, but if this holds "
            "for another couple of weeks the surplus is too big for the training being done.",
        ))

    if intake["days_since_logged"] is None or intake["days_since_logged"] > 2:
        ago = (
            "nothing has been logged yet" if intake["days_since_logged"] is None
            else f"the last logged day was {intake['days_since_logged']} days ago"
        )
        out.append(_finding(
            "warn", "The food log is empty",
            f"A bulk runs on a measured surplus, and {ago}. Without the log there is no telling a 300 kcal "
            "surplus from maintenance — which is the difference between growing and standing still.",
        ))
    elif intake["days_logged"] >= MIN_LOGGED_DAYS and intake["gap_kcal"] is not None:
        gap = intake["gap_kcal"]
        if gap < -200:
            out.append(_finding(
                "warn", f"Under-eating by {abs(gap)} kcal a day",
                f"Averaging {intake['avg_kcal']:,} kcal across {intake['days_logged']} logged days against a "
                f"{intake['target_kcal']:,} kcal target. At that level you are near maintenance, not in a bulk.",
            ))
        elif gap > 300:
            out.append(_finding(
                "info", f"Eating {gap} kcal a day over the target",
                f"Averaging {intake['avg_kcal']:,} kcal against {intake['target_kcal']:,}. A bigger surplus does not "
                "build muscle faster; past the target it is stored as fat.",
            ))
        else:
            out.append(_finding(
                "good", "Intake is on the target",
                f"Averaging {intake['avg_kcal']:,} kcal across {intake['days_logged']} logged days against "
                f"{intake['target_kcal']:,}.",
            ))
        if intake["avg_protein_g"] is not None and intake["protein_target_g"] \
                and intake["avg_protein_g"] < intake["protein_target_g"] * 0.85:
            out.append(_finding(
                "warn", f"Protein short: {intake['avg_protein_g']}g of {intake['protein_target_g']}g",
                "Calories decide whether you gain; protein decides how much of the gain is muscle.",
            ))

    if lifting and lifting["missed"]:
        out.append(_finding(
            "warn", f"{lifting['missed']} planned lifting day(s) missed this week",
            "The surplus only becomes muscle if the lifting asks for it. Without the sessions it is just a surplus.",
        ))
    return out


def build_bulk_view(
    payload: dict,
    goal,
    today: date,
    *,
    split: dict | None = None,
    week_starts_on: int = 0,
) -> dict | None:
    if goal is None:
        return None

    total_days = (goal.end - goal.start).days + 1
    day_number = (today - goal.start).days + 1
    eating = payload.get("eating_target") or {}
    nutrition_view = payload.get("nutrition_view") or {}
    target_kcal = eating.get("daily_target_kcal")
    protein_target = nutrition_view.get("protein_target_g")

    weight = _weight(payload.get("body_comp") or [], goal, today)
    intake = _intake(payload.get("nutrition") or [], today, target_kcal, protein_target)
    creatine = _creatine(goal, payload.get("lifestyle") or [], today)
    lifting = _lifting(payload.get("training") or {}, split or {}, today, week_starts_on)
    findings = _findings(goal, today, weight, intake, creatine, lifting, day_number)

    return {
        "start": iso(goal.start),
        "end": iso(goal.end),
        "started": today >= goal.start,
        "finished": today > goal.end,
        "day_number": max(0, min(day_number, total_days)),
        "total_days": total_days,
        "days_left": max(0, (goal.end - today).days),
        "weeks_left": round(max(0, (goal.end - today).days) / 7, 1),
        "pct_elapsed": round(max(0.0, min(1.0, day_number / total_days)) * 100),
        "daily_surplus_kcal": goal.daily_surplus_kcal,
        "max_body_fat_pct": goal.max_body_fat_pct,
        "weight": weight,
        "intake": intake,
        "creatine": creatine,
        "lifting": lifting,
        "findings": findings,
        "rank": rank_scale.worst(f["rank"] for f in findings) or rank_scale.GOOD,
    }
