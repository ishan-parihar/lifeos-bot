# tests/test_gap_report.py
import pytest
from datetime import datetime, timezone
from services.gap_report import EnrichedGap, classify_severity, classify_gap_type


def test_enriched_gap_creation():
    """EnrichedGap dataclass holds all required fields."""
    gap = EnrichedGap(
        after_entry_id="abc123",
        before_entry_id="def456",
        start=datetime(2026, 6, 10, 22, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc),
        hours=8.0,
        severity="low",
        classification="likely_sleep",
        diet_during=[],
        journal_day={},
        expected_activity=None,
        anomaly_score=0.0,
        severity_reasons=["8h gap during night hours"],
    )
    assert gap.hours == 8.0
    assert gap.severity == "low"
    assert gap.classification == "likely_sleep"


def test_classify_severity_short_night_gap():
    """Short night gap (4-6h) should be info or low severity."""
    severity, reasons = classify_severity(
        hours=5.0,
        start_hour=22,
        is_weekend=False,
        anomaly_score=0.0,
        has_diet_context=False,
        is_sleep_window=True,
    )
    assert severity in ("info", "low")
    assert len(reasons) > 0


def test_classify_severity_long_daytime_gap():
    """Long daytime gap (8-12h) during work hours should be high."""
    severity, reasons = classify_severity(
        hours=10.0,
        start_hour=10,
        is_weekend=False,
        anomaly_score=0.5,
        has_diet_context=False,
        is_sleep_window=False,
    )
    assert severity in ("high", "critical")
    assert any("duration" in r.lower() or "10" in r for r in reasons)


def test_classify_severity_with_diet_context_reduces():
    """Diet entry during gap should reduce severity."""
    sev_without, _ = classify_severity(
        hours=6.0,
        start_hour=12,
        is_weekend=False,
        anomaly_score=0.0,
        has_diet_context=False,
        is_sleep_window=False,
    )
    sev_with, _ = classify_severity(
        hours=6.0,
        start_hour=12,
        is_weekend=False,
        anomaly_score=0.0,
        has_diet_context=True,
        is_sleep_window=False,
    )
    severity_order = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    assert severity_order[sev_with] <= severity_order[sev_without]


def test_classify_gap_type_sleep():
    """Gap overlapping 22:00-06:00 for 4+ hours should be likely_sleep."""
    gap_type = classify_gap_type(
        start_hour=22,
        end_hour=6,
        hours=8.0,
        diet_entries=[],
        is_weekend=False,
    )
    assert gap_type == "likely_sleep"


def test_classify_gap_type_mealtime():
    """Gap with breakfast entry should be likely_mealtime."""
    gap_type = classify_gap_type(
        start_hour=7,
        end_hour=10,
        hours=3.0,
        diet_entries=[{"meal_type": "Breakfast", "timestamp": "2026-06-10T08:30:00"}],
        is_weekend=False,
    )
    assert gap_type == "likely_mealtime"


def test_classify_gap_type_commute():
    """Short gap during commute hours on weekday should be likely_commute."""
    gap_type = classify_gap_type(
        start_hour=8,
        end_hour=9,
        hours=1.0,
        diet_entries=[],
        is_weekend=False,
    )
    assert gap_type == "likely_commute"
