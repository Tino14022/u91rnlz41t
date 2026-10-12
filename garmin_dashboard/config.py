"""Configuration for the dashboard build.

Everything the athlete might want to change lives here as data, so no other
module needs editing to point the build at a different goal, body, or timezone.

The page follows whichever goals are set: a race brings the countdown and the
Running tab, a fat-loss goal brings the cut panels, a bulk brings the Bulk tab.
Leave one as None and its panels disappear rather than showing stale targets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class RaceConfig:
    name: str
    date: date
    distance_km: float


@dataclass(frozen=True)
class AthleteConfig:
    height_cm: int
    weight_kg: float
    protein_g_per_kg: float = 1.8


@dataclass(frozen=True)
class FatLossGoal:
    """A deliberately modest cut, because it runs alongside a race build.

    Faster than about 0.5kg a week starts costing lean mass and long-run quality
    rather than just fat, which is the wrong trade seven weeks out from a race.
    """

    target_body_fat_pct: float = 18.0
    weekly_rate_kg: float = 0.4
    # Protein goes up in a deficit, not down: it is what stops the weight coming
    # off as muscle. 2.0g/kg bodyweight is the usual floor while cutting.
    protein_g_per_kg: float = 2.0
    # Above this share of bodyweight per week, loss is too fast to be mostly fat.
    max_safe_weekly_pct: float = 1.0


@dataclass(frozen=True)
class BulkGoal:
    """A lean bulk: a small surplus over measured burn, not "eat everything".

    Starting near 19% body fat, a large surplus mostly adds fat and buys a
    longer cut afterwards. The surplus rides on the athlete's own trailing
    burn, so the eating target follows what the watch measures.
    """

    start: date
    end: date
    target_gain_kg: float = 5.0
    daily_surplus_kcal: int = 300
    # Protein need per kg is a little lower in a surplus than in a cut, but the
    # 2.0g/kg habit is already established and costs nothing to keep.
    protein_g_per_kg: float = 2.0
    # Weekly gain band. Below it the surplus is not landing; above it the
    # extra is mostly fat.
    weekly_gain_min_kg: float = 0.25
    weekly_gain_max_kg: float = 0.5
    # Past this the bulk has done its job and it is time to cut.
    max_body_fat_pct: float = 21.0
    creatine_start: date | None = None
    creatine_dose_g: float = 5.0
    # Without a loading phase, 3-5g a day saturates muscle in about four weeks.
    creatine_saturation_days: int = 28


@dataclass(frozen=True)
class WindowConfig:
    """How far back each family of metrics is fetched, in weeks."""

    trend: int = 12
    recovery: int = 4
    recent_runs: int = 4
    # Garmin's daily-summary endpoint is one call per day, so this stays modest.
    calories: int = 5


@dataclass(frozen=True)
class Settings:
    # None when no race is booked: the countdown, the long-run ladder and the
    # Running tab all go with it.
    race: RaceConfig | None
    athlete: AthleteConfig
    # Set to None to stop tracking a cut; the panel disappears with it.
    goal: FatLossGoal | None = field(default_factory=FatLossGoal)
    # Set to track a bulk; the Bulk tab and the eating target appear with it.
    bulk: BulkGoal | None = None
    windows: WindowConfig = field(default_factory=WindowConfig)
    # The build runs on a UTC CI runner; without this, "today" flips over at
    # 02:00 local in summer and the dashboard shows yesterday for two hours.
    # Held as a name and resolved lazily: Windows ships no system tz database,
    # so constructing ZoneInfo at import time makes the module unimportable
    # there even for code paths that never ask what day it is.
    timezone_name: str = "Europe/Warsaw"
    # First day of the week, as Python weekday numbers (Mon=0 .. Sun=6).
    week_starts_on: int = 0
    # Days dropped from the nutrition rolling average — not deleted from the
    # log, just excluded from "week_avg_*" so one outlier (a pre-cut blowout,
    # a birthday) doesn't drag every day after it for the next week.
    excluded_nutrition_dates: frozenset[date] = field(default_factory=frozenset)

    def tzinfo(self):
        try:
            return ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, KeyError):
            print(
                f"  ! no tz database entry for {self.timezone_name}; "
                "falling back to UTC (install the 'tzdata' package)"
            )
            return timezone.utc

    def today(self) -> date:
        return datetime.now(self.tzinfo()).date()


DEFAULT_SETTINGS = Settings(
    # The Wizz Air Half Marathon (2026-10-04, 21.1km) is done; no race booked.
    race=None,
    athlete=AthleteConfig(height_cm=192, weight_kg=95),
    goal=None,
    # Winter bulk, agreed 2026-10-12: no running, upper-body split, creatine.
    bulk=BulkGoal(
        start=date(2026, 10, 12),
        end=date(2027, 3, 1),
        creatine_start=date(2026, 10, 6),
    ),
    # 2026-08-14: the day before the cut started, well above normal intake.
    # Kept in the log, just left out of the rolling average.
    excluded_nutrition_dates=frozenset({date(2026, 8, 14)}),
)
