"""Enriched gap report service.

Wraps the existing activity gap detection with cross-log context from
journal, diet, and financial services. Adds severity classification
and gap type identification.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EnrichedGap:
    """Activity gap enriched with cross-log context and classification."""

    after_entry_id: str | None
    before_entry_id: str | None
    start: datetime
    end: datetime
    hours: float
    severity: str  # "info" | "low" | "medium" | "high" | "critical"
    classification: str  # "likely_sleep" | "likely_mealtime" | "likely_commute" | "recurring_break" | "untracked" | "unknown" | "boundary_gap"
    diet_during: list[dict] = field(default_factory=list)
    journal_day: dict = field(default_factory=dict)
    expected_activity: str | None = None
    anomaly_score: float = 0.0
    severity_reasons: list[str] = field(default_factory=list)


SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _duration_score(hours: float) -> int:
    """Duration component (0-4)."""
    if hours < 4:
        return 0
    elif hours < 6:
        return 1
    elif hours < 8:
        return 2
    elif hours < 12:
        return 3
    else:
        return 4


def _time_of_day_modifier(start_hour: int, is_sleep_window: bool) -> float:
    """Time-of-day modifier (-30% to +20%)."""
    if is_sleep_window:
        return -1.2  # -30% of 4
    if 9 <= start_hour < 17:
        return 0.8  # +20% of 4
    if 17 <= start_hour < 22:
        return 0.4  # +10% of 4
    return 0.0


def _day_of_week_modifier(is_weekend: bool) -> float:
    """Day-of-week modifier (-10% to +10%)."""
    return -0.4 if is_weekend else 0.4  # ±10% of 4


def _anomaly_modifier(anomaly_score: float) -> float:
    """Anomaly score modifier (0-30% of max)."""
    return min(anomaly_score * 1.2, 1.2)  # Cap at 30% of 4


def _cross_log_modifier(has_diet_context: bool, is_sleep_window: bool) -> float:
    """Cross-log explanation modifier (-50% to 0%)."""
    modifier = 0.0
    if is_sleep_window:
        modifier -= 2.0  # -50% of 4
    if has_diet_context:
        modifier -= 0.8  # -20% of 4
    return modifier


def classify_severity(
    hours: float,
    start_hour: int,
    is_weekend: bool,
    anomaly_score: float,
    has_diet_context: bool,
    is_sleep_window: bool,
) -> tuple[str, list[str]]:
    """Calculate severity score and reasons for a gap.

    Returns (severity_label, list_of_reasons).
    """
    reasons = []

    dur = _duration_score(hours)
    reasons.append(f"Duration: {hours:.1f}h (score={dur})")

    tod_mod = _time_of_day_modifier(start_hour, is_sleep_window)
    if tod_mod != 0:
        reasons.append(f"Time-of-day modifier: {tod_mod:+.1f}")

    dow_mod = _day_of_week_modifier(is_weekend)
    if dow_mod != 0:
        reasons.append(f"Day-of-week modifier: {dow_mod:+.1f}")

    anom_mod = _anomaly_modifier(anomaly_score)
    if anom_mod > 0:
        reasons.append(f"Anomaly score: {anomaly_score:.2f} (modifier={anom_mod:+.1f})")

    cross_mod = _cross_log_modifier(has_diet_context, is_sleep_window)
    if cross_mod < 0:
        reasons.append(f"Cross-log explanation (modifier={cross_mod:+.1f})")

    raw_score = dur + tod_mod + dow_mod + anom_mod + cross_mod
    raw_score = max(0.0, raw_score)

    if raw_score < 0.5:
        severity = "info"
    elif raw_score < 1.5:
        severity = "low"
    elif raw_score < 2.5:
        severity = "medium"
    elif raw_score < 3.5:
        severity = "high"
    else:
        severity = "critical"

    reasons.insert(0, f"Raw score: {raw_score:.2f} → {severity}")
    return severity, reasons


def classify_gap_type(
    start_hour: int,
    end_hour: int,
    hours: float,
    diet_entries: list[dict],
    is_weekend: bool,
) -> str:
    """Classify a gap into a human-readable type.

    Priority order:
    1. Sleep: overlaps 22:00-06:00 AND >= 4h
    2. Mealtime: diet entry for Breakfast/Lunch/Dinner during gap
    3. Commute: 08:00-09:30 or 17:00-18:30 weekdays, < 2h
    4. Untracked: has activity before/after but no explanation
    5. Unknown: everything else
    """
    # Sleep detection
    if hours >= 4.0:
        # Check if gap overlaps 22:00-06:00
        if start_hour >= 22 or end_hour <= 6 or (start_hour < 6 and end_hour > 22):
            return "likely_sleep"
        # Multi-day gap that covers night
        if hours >= 8.0:
            return "likely_sleep"

    # Mealtime detection
    meal_types = {"breakfast", "lunch", "dinner"}
    for entry in diet_entries:
        meal = (entry.get("meal_type") or "").lower()
        if meal in meal_types:
            return "likely_mealtime"

    # Commute detection
    if not is_weekend and hours < 2.0:
        if 8 <= start_hour < 10 or 17 <= start_hour < 19:
            return "likely_commute"

    # If we have diet entries but none matched meal types
    if diet_entries:
        return "untracked"

    return "unknown"


async def get_enriched_gaps(
    entries: list[dict],
    window_start: datetime,
    window_end: datetime,
    *,
    threshold_minutes: int = 240,
    diet_service=None,
    journal_service=None,
    insights_service=None,
) -> list[EnrichedGap]:
    """Get activity gaps enriched with cross-log context.

    Args:
        entries: Sorted activity log entries (dicts with id, start_time, end_time).
        window_start: Start of analysis window.
        window_end: End of analysis window.
        threshold_minutes: Minimum gap duration to report (default 240 = 4h).
        diet_service: Optional diet service for cross-log context.
        journal_service: Optional journal service for cross-log context.
        insights_service: Optional insights service for anomaly scores.

    Returns:
        List of EnrichedGap objects, sorted by start time.
    """
    from services.activity import get_gaps

    # Get raw gaps from existing service
    raw_gaps = get_gaps(
        entries,
        threshold_minutes=threshold_minutes,
        window_start=window_start,
        window_end=window_end,
    )

    if not raw_gaps:
        return []

    # Gather cross-log data
    diet_entries = []
    journal_entries = []
    anomaly_scores = {}

    if diet_service:
        try:
            diet_entries = await diet_service.get_diet_entries(
                date_from=window_start.date(),
                date_to=window_end.date(),
            ) or []
        except Exception as e:
            logger.warning("Failed to fetch diet entries for gap enrichment: %s", e)

    if journal_service:
        try:
            journal_entries = await journal_service.get_entries(
                date_from=window_start.date(),
                date_to=window_end.date(),
            ) or []
        except Exception as e:
            logger.warning("Failed to fetch journal entries for gap enrichment: %s", e)

    if insights_service:
        try:
            patterns = await insights_service.get_gap_patterns()
            anomaly_scores = patterns.get("anomaly_scores", {})
        except Exception as e:
            logger.warning("Failed to fetch insights for gap enrichment: %s", e)

    enriched = []
    for gap in raw_gaps:
        start: datetime = gap["start"]
        end: datetime = gap["end"]
        hours: float = gap["hours"]

        # Determine time context
        start_hour = start.hour
        end_hour = end.hour
        is_weekend = start.weekday() >= 5

        # Check if gap overlaps sleep window (22:00-06:00)
        is_sleep_window = _overlaps_sleep_window(start, end)

        # Find diet entries during this gap
        diet_during = [
            d for d in diet_entries
            if _entry_overlaps(d, start, end)
        ]
        has_diet_context = len(diet_during) > 0

        # Find journal entries for this day
        journal_day = _find_journal_for_date(journal_entries, start.date())

        # Get anomaly score (default 0.0)
        anomaly_score = anomaly_scores.get(gap.get("after_entry_id", ""), 0.0)

        # Classify
        severity, reasons = classify_severity(
            hours=hours,
            start_hour=start_hour,
            is_weekend=is_weekend,
            anomaly_score=anomaly_score,
            has_diet_context=has_diet_context,
            is_sleep_window=is_sleep_window,
        )

        classification = classify_gap_type(
            start_hour=start_hour,
            end_hour=end_hour,
            hours=hours,
            diet_entries=diet_during,
            is_weekend=is_weekend,
        )

        # Mark boundary gaps
        if gap.get("boundary") in ("start", "end"):
            classification = "boundary_gap"

        enriched.append(EnrichedGap(
            after_entry_id=gap.get("after_entry_id"),
            before_entry_id=gap.get("before_entry_id"),
            start=start,
            end=end,
            hours=hours,
            severity=severity,
            classification=classification,
            diet_during=diet_during,
            journal_day=journal_day,
            expected_activity=None,
            anomaly_score=anomaly_score,
            severity_reasons=reasons,
        ))

    return enriched


def _overlaps_sleep_window(start: datetime, end: datetime) -> bool:
    """Check if a time range overlaps 22:00-06:00."""
    # Simple check: if start is after 22:00 or end is before 06:00
    if start.hour >= 22 or end.hour <= 6:
        return True
    # Multi-day gap
    if (end - start).days >= 1:
        return True
    return False


def _entry_overlaps(entry: dict, start: datetime, end: datetime) -> bool:
    """Check if a diet/journal entry timestamp falls within a gap."""
    entry_time_str = entry.get("timestamp") or entry.get("created_at")
    if not entry_time_str:
        return False
    try:
        if isinstance(entry_time_str, str):
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
        else:
            entry_time = entry_time_str
        return start <= entry_time <= end
    except (ValueError, TypeError):
        return False


def _find_journal_for_date(journal_entries: list[dict], target_date) -> dict:
    """Find journal entries for a specific date."""
    for entry in journal_entries:
        entry_date = entry.get("date") or entry.get("created_at")
        if entry_date:
            try:
                if isinstance(entry_date, str):
                    entry_date = datetime.fromisoformat(entry_date.replace("Z", "+00:00")).date()
                elif isinstance(entry_date, datetime):
                    entry_date = entry_date.date()
                if entry_date == target_date:
                    return entry
            except (ValueError, TypeError):
                continue
    return {}
