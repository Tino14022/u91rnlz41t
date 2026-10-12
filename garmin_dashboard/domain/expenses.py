"""Spending: where the money went, and how the current paycheck is holding up.

Amounts are MKD denars. An expense is money out (a refund is logged negative);
income is a paycheck, either received or — dated in the future — expected.
"""
from __future__ import annotations

import calendar
from datetime import date

from . import rank as rank_scale
from .formatting import iso, parse_iso, week_start

UNCATEGORISED = "other"
# Spending this far ahead of the calendar is worth a colour change; a few
# percent either way is just which day the rent left the account.
PACE_FAIR = 1.0
PACE_BAD = 1.15


def _rows(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries or []:
        d = parse_iso(e.get("date"))
        amount = e.get("amount_den")
        if d is None or not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        out.append({**e, "day": d})
    return sorted(out, key=lambda r: r["day"])


def _category(row: dict) -> str:
    return (row.get("category") or UNCATEGORISED).strip().lower() or UNCATEGORISED


def _by_category(rows: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for r in rows:
        bucket = totals.setdefault(_category(r), {"total": 0.0, "count": 0})
        bucket["total"] += r["amount_den"]
        bucket["count"] += 1
    grand = sum(b["total"] for b in totals.values())
    out = [
        {
            "category": name,
            "total_den": round(b["total"]),
            "count": b["count"],
            "pct": round(b["total"] / grand * 100) if grand > 0 else 0,
        }
        for name, b in totals.items()
    ]
    return sorted(out, key=lambda c: -c["total_den"])


def _same_day_next_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _paycheck(expenses: list[dict], income: list[dict], today: date) -> dict | None:
    """The pay period in progress, and the next paycheck on its way."""
    if not income:
        return None
    received = [i for i in income if i["day"] <= today]
    upcoming = [i for i in income if i["day"] > today]
    out: dict = {"current": None, "next": None}

    if upcoming:
        nxt = upcoming[0]
        out["next"] = {
            "date": iso(nxt["day"]),
            "amount_den": round(nxt["amount_den"]),
            "source": nxt.get("source"),
            "days_until": (nxt["day"] - today).days,
        }

    if received:
        last = received[-1]
        period_end = upcoming[0]["day"] if upcoming else _same_day_next_month(last["day"])
        spent = sum(e["amount_den"] for e in expenses if last["day"] <= e["day"] <= today)
        amount = last["amount_den"]
        remaining = amount - spent
        period_days = max(1, (period_end - last["day"]).days)
        elapsed = min(period_days, (today - last["day"]).days + 1)
        days_left = max(0, (period_end - today).days)

        # Share of the money gone against share of the period gone. On pace is
        # 1.0; above it the paycheck runs out before the next one lands.
        pace = (spent / amount) / (elapsed / period_days) if amount > 0 else None
        if remaining < 0:
            rank = rank_scale.TERRIBLE
        elif pace is None or pace <= PACE_FAIR:
            rank = rank_scale.GOOD
        elif pace <= PACE_BAD:
            rank = rank_scale.FAIR
        else:
            rank = rank_scale.BAD

        out["current"] = {
            "date": iso(last["day"]),
            "amount_den": round(amount),
            "source": last.get("source"),
            "period_end": iso(period_end),
            # Without a next paycheck on file the period is assumed monthly.
            "period_end_assumed": not upcoming,
            "spent_den": round(spent),
            "remaining_den": round(remaining),
            "pct_spent": round(min(1.5, spent / amount) * 100) if amount > 0 else None,
            "pct_elapsed": round(elapsed / period_days * 100),
            "days_left": days_left,
            "daily_allowance_den": round(remaining / days_left) if days_left > 0 else round(remaining),
            "pace": round(pace, 2) if pace is not None else None,
            "rank": rank,
        }
    return out


def build_expenses_view(
    expenses: list[dict],
    income: list[dict],
    today: date,
    *,
    week_starts_on: int = 0,
) -> dict | None:
    rows = [r for r in _rows(expenses) if r["day"] <= today]
    pay = _rows(income)
    if not rows and not pay:
        return None

    paycheck = _paycheck(rows, pay, today)
    if not rows:
        return {"entry_count": 0, "paycheck": paycheck}

    wk_start = week_start(today, week_starts_on)
    in_week = [r for r in rows if r["day"] >= wk_start]
    in_month = [r for r in rows if (r["day"].year, r["day"].month) == (today.year, today.month)]
    prev_year, prev_month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    in_prev_month = [r for r in rows if (r["day"].year, r["day"].month) == (prev_year, prev_month)]

    by_date: dict[str, float] = {}
    for r in rows:
        by_date[iso(r["day"])] = by_date.get(iso(r["day"]), 0) + r["amount_den"]

    month_total = sum(r["amount_den"] for r in in_month)
    biggest = max(in_month, key=lambda r: r["amount_den"]) if in_month else None
    return {
        "entry_count": len(rows),
        "days_logged": len(by_date),
        "tracking_since": iso(rows[0]["day"]),
        "total_den": round(sum(r["amount_den"] for r in rows)),
        "week_total_den": round(sum(r["amount_den"] for r in in_week)),
        "month_total_den": round(month_total),
        "prev_month_total_den": round(sum(r["amount_den"] for r in in_prev_month)) if in_prev_month else None,
        # Averaged over the days of the month so far, spending days or not —
        # the question is what a day costs, not what a spending day costs.
        "month_daily_avg_den": round(month_total / today.day),
        "by_date": {d: round(v) for d, v in by_date.items()},
        "month_by_category": _by_category(in_month),
        "all_time_by_category": _by_category(rows),
        "biggest_this_month": {
            "date": iso(biggest["day"]),
            "amount_den": round(biggest["amount_den"]),
            "category": _category(biggest),
            "note": biggest.get("note"),
        } if biggest else None,
        "paycheck": paycheck,
    }
