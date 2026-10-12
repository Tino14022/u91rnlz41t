"""Nutrition composition views: macro plate, energy flow, protein distribution."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import rank as rank_scale
from .formatting import parse_iso
from .goals import KCAL_PER_KG_FAT
from .nutrition import repair_day, typical_daily_bmr

KCAL = {"protein": 4, "carbs": 4, "fat": 9}
# Long enough to average out day-to-day noise, close to what Garmin Connect's
# own "Avg Total" widget shows over its 4-week view.
EATING_BUDGET_WINDOW_DAYS = 28
# Above this much over budget the day is no longer "a bit tight" — it is a
# real overshoot worth flagging distinctly from a token few kcal.
BUDGET_OVERSHOOT_KCAL = 150
# In a bulk the miss that matters is under-eating; this far over the target is
# flagged too, because past it the extra is fat rather than muscle.
TARGET_OVERSHOOT_KCAL = 300
# A day counts as having hit the eating target from this share of it upward.
TARGET_HIT_RATIO = 0.95
MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack"]
# Beyond roughly this much in one sitting, extra protein contributes little to
# muscle protein synthesis — distribution matters, not just the daily total.
PER_MEAL_CEILING_G = 40


def _day_totals(nutrition: list[dict], on: str) -> dict:
    rows = [n for n in nutrition if n.get("date") == on]
    return {
        "calories": sum(n.get("calories") or 0 for n in rows),
        "protein": sum(n.get("protein_g") or 0 for n in rows),
        "carbs": sum(n.get("carbs_g") or 0 for n in rows),
        "fat": sum(n.get("fat_g") or 0 for n in rows),
        "entries": rows,
    }


def build_macro_plate(payload: dict, today: date) -> dict | None:
    """Actual macro split against the split your targets imply."""
    nutrition = [n for n in payload.get("nutrition") or [] if n.get("date")]
    if not nutrition:
        return None
    latest = max(n["date"] for n in nutrition)
    t = _day_totals(nutrition, latest)
    from_macros = sum(t[m] * KCAL[m] for m in KCAL)
    if from_macros <= 0:
        return None

    nv = payload.get("nutrition_view") or {}
    protein_target = nv.get("protein_target_g") or 0
    # Target plate: protein fixed by bodyweight, fat at 25% of intake, the rest
    # carbs — the usual construction for someone training hard in a deficit.
    target_kcal = nv.get("week_avg_burn_kcal") or t["calories"] or 2500
    target_fat_g = target_kcal * 0.25 / KCAL["fat"]
    target_carb_g = max(0, (target_kcal - protein_target * KCAL["protein"] - target_fat_g * KCAL["fat"]) / KCAL["carbs"])

    def slice_(name, grams, target_g):
        kcal = grams * KCAL[name]
        return {
            "macro": name,
            "grams": round(grams),
            "kcal": round(kcal),
            "pct": round(kcal / from_macros * 100),
            "target_g": round(target_g),
            "delta_g": round(grams - target_g),
        }

    slices = [
        slice_("protein", t["protein"], protein_target),
        slice_("carbs", t["carbs"], target_carb_g),
        slice_("fat", t["fat"], target_fat_g),
    ]
    return {
        "date": latest,
        "slices": slices,
        "total_kcal": round(t["calories"]),
        "kcal_from_macros": round(from_macros),
        # A gap here means the logged macros do not add up to the logged calories.
        "unaccounted_kcal": round(t["calories"] - from_macros),
    }


def trailing_burn(
    calorie_trend: list[dict], today: date, days: int = EATING_BUDGET_WINDOW_DAYS
) -> tuple[float, list[float]] | None:
    """Average total burn over the complete days before today, and those days.

    Partial days are topped up the same way the nutrition view repairs them,
    so a day the watch was off for does not drag the average down.
    """
    if not calorie_trend:
        return None
    typical_bmr = typical_daily_bmr(calorie_trend)
    window_start = today - timedelta(days=days)
    totals = []
    for c in calorie_trend:
        d = parse_iso(c.get("date"))
        if d is None or d < window_start or d >= today:
            continue
        repaired = repair_day(c, typical_bmr)
        if repaired is not None:
            totals.append(repaired["total_kcal"])
    if not totals:
        return None
    return statistics.fmean(totals), totals


def build_eating_budget(
    payload: dict, today: date, goal, *, days: int = EATING_BUDGET_WINDOW_DAYS
) -> dict | None:
    """How much more there is to eat today and stay inside the cut.

    Benchmark is the athlete's own trailing average total burn (basal +
    active) — the same figure the Garmin Connect app's own "Avg Total" widget
    reports, computed here instead of copied in so it keeps moving with the
    data. Partial days are topped up the same way the nutrition view repairs
    them, so a day the watch was off for does not drag the average down.
    """
    if goal is None:
        return None
    benchmark = trailing_burn(payload.get("calorie_trend") or [], today, days)
    if benchmark is None:
        return None
    benchmark_kcal, totals = benchmark
    daily_deficit_kcal = round(goal.weekly_rate_kg * KCAL_PER_KG_FAT / 7)
    daily_budget_kcal = round(benchmark_kcal - daily_deficit_kcal)

    nutrition_view = payload.get("nutrition_view") or {}
    eaten_today_kcal = round(nutrition_view.get("today_intake_kcal") or 0)
    remaining_kcal = daily_budget_kcal - eaten_today_kcal

    if remaining_kcal >= 0:
        rank = rank_scale.GOOD
    elif remaining_kcal >= -BUDGET_OVERSHOOT_KCAL:
        rank = rank_scale.FAIR
    else:
        rank = rank_scale.BAD

    return {
        "benchmark_kcal": round(benchmark_kcal),
        "benchmark_days": len(totals),
        "benchmark_window_days": days,
        "daily_deficit_kcal": daily_deficit_kcal,
        "daily_budget_kcal": daily_budget_kcal,
        "eaten_today_kcal": eaten_today_kcal,
        "remaining_kcal": remaining_kcal,
        "over_budget": remaining_kcal < 0,
        # Capped so a big overshoot fills the bar rather than running off it.
        "pct_used": round(min(eaten_today_kcal / daily_budget_kcal, 1.5) * 100)
        if daily_budget_kcal
        else None,
        "rank": rank,
    }


def build_eating_target(
    payload: dict, today: date, bulk, *, days: int = EATING_BUDGET_WINDOW_DAYS
) -> dict | None:
    """How much there is still to eat today to hold the bulk's surplus.

    The mirror image of the eating budget: same trailing-burn benchmark, but
    the surplus is added and the number to watch is what is left to eat, not
    what is left before going over.
    """
    if bulk is None:
        return None
    benchmark = trailing_burn(payload.get("calorie_trend") or [], today, days)
    if benchmark is None:
        return None
    benchmark_kcal, totals = benchmark
    # Rounded to the nearest 50: the benchmark moves a few kcal every day and a
    # target that reads 3,137 one morning and 3,142 the next is noise.
    daily_target_kcal = int(round((benchmark_kcal + bulk.daily_surplus_kcal) / 50) * 50)

    nutrition_view = payload.get("nutrition_view") or {}
    eaten_today_kcal = round(nutrition_view.get("today_intake_kcal") or 0)
    remaining_kcal = daily_target_kcal - eaten_today_kcal
    protein_target_g = nutrition_view.get("protein_target_g")
    protein_today_g = round(nutrition_view.get("today_protein_g") or 0)

    hit = eaten_today_kcal >= daily_target_kcal * TARGET_HIT_RATIO
    over = eaten_today_kcal > daily_target_kcal + TARGET_OVERSHOOT_KCAL
    return {
        "benchmark_kcal": round(benchmark_kcal),
        "benchmark_days": len(totals),
        "benchmark_window_days": days,
        "daily_surplus_kcal": bulk.daily_surplus_kcal,
        "daily_target_kcal": daily_target_kcal,
        "eaten_today_kcal": eaten_today_kcal,
        "remaining_kcal": remaining_kcal,
        "hit": hit,
        "over": over,
        "pct_eaten": round(min(eaten_today_kcal / daily_target_kcal, 1.5) * 100)
        if daily_target_kcal
        else None,
        "protein_target_g": protein_target_g,
        "protein_today_g": protein_today_g,
        "protein_remaining_g": (protein_target_g - protein_today_g)
        if protein_target_g
        else None,
        # The day is still open, so short of the target is not yet a failure.
        "rank": rank_scale.FAIR if over or not hit else rank_scale.GOOD,
    }


def build_protein_distribution(payload: dict, today: date, *, days: int = 7) -> dict | None:
    """Protein by meal — a daily total landing in one sitting is not the same
    as the same total spread across the day."""
    nutrition = [n for n in payload.get("nutrition") or [] if n.get("date") and n.get("protein_g")]
    if not nutrition:
        return None
    cutoff = (today - timedelta(days=days)).isoformat()
    recent = [n for n in nutrition if n["date"] >= cutoff]
    if not recent:
        recent = nutrition[-10:]

    by_meal: dict[str, list[float]] = {}
    for n in recent:
        meal = (n.get("meal") or "snack").lower()
        by_meal.setdefault(meal, []).append(n.get("protein_g") or 0)

    meals = []
    for meal in MEAL_ORDER:
        values = by_meal.get(meal)
        if not values:
            continue
        avg = statistics.fmean(values)
        meals.append({
            "meal": meal,
            "avg_protein_g": round(avg),
            "count": len(values),
            "over_ceiling": avg > PER_MEAL_CEILING_G,
        })
    for meal, values in by_meal.items():
        if meal not in MEAL_ORDER:
            meals.append({
                "meal": meal,
                "avg_protein_g": round(statistics.fmean(values)),
                "count": len(values),
                "over_ceiling": statistics.fmean(values) > PER_MEAL_CEILING_G,
            })
    if not meals:
        return None

    dates = {n["date"] for n in recent}
    daily = [sum(n.get("protein_g") or 0 for n in recent if n["date"] == d) for d in dates]
    target = (payload.get("nutrition_view") or {}).get("protein_target_g")
    biggest = max(meals, key=lambda m: m["avg_protein_g"])
    return {
        "meals": meals,
        "ceiling_g": PER_MEAL_CEILING_G,
        "avg_daily_g": round(statistics.fmean(daily)) if daily else 0,
        "target_g": target,
        "days": len(dates),
        "biggest_meal": biggest["meal"],
        # Front-loading everything into one meal wastes some of the total.
        "concentrated": biggest["avg_protein_g"] > PER_MEAL_CEILING_G * 1.5,
    }
