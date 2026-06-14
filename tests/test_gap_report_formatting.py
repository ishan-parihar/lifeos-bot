# tests/test_gap_report_formatting.py
import pytest
from datetime import datetime, timezone
from services.gap_report import EnrichedGap
from bot.formatting import render_enriched_gap_report


def _make_gap(**kwargs) -> EnrichedGap:
    """Helper to create test EnrichedGap with defaults."""
    defaults = dict(
        after_entry_id="abc",
        before_entry_id="def",
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
    defaults.update(kwargs)
    return EnrichedGap(**defaults)


def test_render_enriched_gap_report_empty():
    """Empty gap list produces a clean 'no gaps' message."""
    result = render_enriched_gap_report([])
    assert "no gaps" in result.lower() or "✅" in result


def test_render_enriched_gap_report_single_gap():
    """Single gap renders with severity emoji and classification."""
    gap = _make_gap()
    result = render_enriched_gap_report([gap])
    assert "likely_sleep" in result.lower() or "😴" in result
    assert "8.0h" in result or "8h" in result


def test_render_enriched_gap_report_severity_emoji():
    """Each severity level maps to correct emoji."""
    for sev, emoji in [("info", "ℹ️"), ("low", "🟢"), ("medium", "🟡"), ("high", "🟠"), ("critical", "🔴")]:
        gap = _make_gap(severity=sev)
        result = render_enriched_gap_report([gap])
        assert emoji in result


def test_render_enriched_gap_report_diet_context():
    """Gap with diet entries shows meal context."""
    gap = _make_gap(
        classification="likely_mealtime",
        diet_during=[{"meal_type": "Lunch", "timestamp": "2026-06-10T12:30:00"}],
    )
    result = render_enriched_gap_report([gap])
    assert "lunch" in result.lower() or "🍽" in result


def test_render_enriched_gap_report_truncation():
    """Report respects Telegram 4096 char limit."""
    # Create 20 gaps to test truncation
    gaps = [_make_gap(hours=i + 4, severity="medium") for i in range(20)]
    result = render_enriched_gap_report(gaps)
    assert len(result) <= 4096


def test_render_enriched_gap_report_summary_header():
    """Report starts with summary line showing total count and severity breakdown."""
    gaps = [
        _make_gap(severity="low"),
        _make_gap(severity="high"),
        _make_gap(severity="high"),
    ]
    result = render_enriched_gap_report(gaps)
    assert "3" in result  # Total count
    assert "high" in result.lower() or "🟠" in result
