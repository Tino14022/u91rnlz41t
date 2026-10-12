"""Expenses: totals, categories, and how the current paycheck is holding up."""
from __future__ import annotations

from datetime import date

from garmin_dashboard.domain.expenses import build_expenses_view

TODAY = date(2026, 11, 18)  # a Wednesday


def spend(day: str, amount, category: str | None = None, note: str | None = None) -> dict:
    row = {"date": day, "amount_den": amount}
    if category:
        row["category"] = category
    if note:
        row["note"] = note
    return row


def pay(day: str, amount=55500) -> dict:
    return {"date": day, "amount_den": amount, "source": "paycheck"}


def view(expenses=(), income=(), today=TODAY):
    return build_expenses_view(list(expenses), list(income), today, week_starts_on=0)


def test_nothing_logged_means_no_view():
    assert view() is None


def test_an_expected_paycheck_alone_is_a_countdown():
    v = view(income=[pay("2026-11-04")], today=date(2026, 10, 12))
    assert v["entry_count"] == 0
    assert v["paycheck"]["current"] is None
    assert v["paycheck"]["next"] == {
        "date": "2026-11-04", "amount_den": 55500, "source": "paycheck", "days_until": 23,
    }


def test_totals_cover_the_week_the_month_and_everything():
    rows = [
        spend("2026-10-30", 1000),   # last month
        spend("2026-11-03", 2000),   # this month, earlier week
        spend("2026-11-16", 300),    # Monday of this week
        spend("2026-11-18", 200),    # today
    ]
    v = view(rows)
    assert v["week_total_den"] == 500
    assert v["month_total_den"] == 2500
    assert v["prev_month_total_den"] == 1000
    assert v["total_den"] == 3500
    assert v["tracking_since"] == "2026-10-30"
    assert v["entry_count"] == 4 and v["days_logged"] == 4


def test_daily_average_spreads_over_every_day_of_the_month_so_far():
    v = view([spend("2026-11-03", 1800)])
    assert v["month_daily_avg_den"] == 100  # 1800 over 18 days


def test_same_day_entries_are_summed_on_the_calendar():
    v = view([spend("2026-11-10", 200), spend("2026-11-10", 350)])
    assert v["by_date"] == {"2026-11-10": 550}


def test_rows_without_a_usable_date_or_amount_are_skipped():
    rows = [
        spend("2026-11-10", 400),
        spend("not-a-date", 999),
        {"date": "2026-11-11"},
        {"date": "2026-11-12", "amount_den": "lots"},
        {"date": "2026-11-13", "amount_den": True},
    ]
    assert view(rows)["total_den"] == 400


def test_expenses_dated_in_the_future_do_not_count_yet():
    v = view([spend("2026-11-10", 400), spend("2026-12-01", 5000)])
    assert v["total_den"] == 400


def test_categories_are_ranked_and_merged_case_insensitively():
    rows = [
        spend("2026-11-02", 3000, "Food"),
        spend("2026-11-05", 1000, "food"),
        spend("2026-11-06", 1800, "gym"),
        spend("2026-11-07", 200),
    ]
    cats = view(rows)["month_by_category"]
    assert [c["category"] for c in cats] == ["food", "gym", "other"]
    assert cats[0] == {"category": "food", "total_den": 4000, "count": 2, "pct": 67}


def test_biggest_expense_of_the_month_is_named():
    rows = [spend("2026-11-02", 300, "food"), spend("2026-11-09", 1800, "gym", "membership")]
    assert view(rows)["biggest_this_month"] == {
        "date": "2026-11-09", "amount_den": 1800, "category": "gym", "note": "membership",
    }


def test_a_refund_nets_against_spending():
    v = view([spend("2026-11-02", 2000, "clothes"), spend("2026-11-04", -500, "clothes")])
    assert v["month_total_den"] == 1500


# --------------------------------------------------------------- paycheck

def test_a_received_paycheck_becomes_a_running_balance():
    rows = [spend("2026-11-03", 9999), spend("2026-11-04", 5500), spend("2026-11-10", 10000)]
    v = view(rows, income=[pay("2026-11-04"), pay("2026-12-04")])
    cur = v["paycheck"]["current"]
    assert cur["spent_den"] == 15500           # the day before payday is not in it
    assert cur["remaining_den"] == 40000
    assert cur["period_end"] == "2026-12-04"
    assert cur["period_end_assumed"] is False
    assert cur["days_left"] == 16
    assert cur["daily_allowance_den"] == 2500
    assert v["paycheck"]["next"]["days_until"] == 16


def test_without_a_next_paycheck_the_period_is_assumed_monthly():
    cur = view([spend("2026-11-05", 100)], income=[pay("2026-11-04")])["paycheck"]["current"]
    assert cur["period_end"] == "2026-12-04"
    assert cur["period_end_assumed"] is True


def test_a_month_end_payday_is_clamped_to_the_next_month():
    cur = view([spend("2027-02-01", 100)], income=[pay("2027-01-31")], today=date(2027, 2, 2))["paycheck"]["current"]
    assert cur["period_end"] == "2027-02-28"


def test_spending_slower_than_the_calendar_ranks_good():
    # 15 of 30 days gone, 30% of the money gone.
    cur = view([spend("2026-11-10", 16650)], income=[pay("2026-11-04"), pay("2026-12-04")])["paycheck"]["current"]
    assert cur["pct_elapsed"] == 50
    assert cur["pct_spent"] == 30
    assert cur["rank"] == "good"


def test_spending_ahead_of_the_calendar_ranks_bad():
    cur = view([spend("2026-11-10", 44400)], income=[pay("2026-11-04"), pay("2026-12-04")])["paycheck"]["current"]
    assert cur["pct_spent"] == 80
    assert cur["rank"] == "bad"


def test_spending_past_the_paycheck_ranks_terrible():
    cur = view([spend("2026-11-10", 60000)], income=[pay("2026-11-04"), pay("2026-12-04")])["paycheck"]["current"]
    assert cur["remaining_den"] == -4500
    assert cur["rank"] == "terrible"


def test_the_latest_received_paycheck_is_the_current_one():
    v = view([spend("2026-11-06", 500)], income=[pay("2026-10-04", 50000), pay("2026-11-04")])
    assert v["paycheck"]["current"]["amount_den"] == 55500
    assert v["paycheck"]["next"] is None
