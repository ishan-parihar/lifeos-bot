"""Integration tests for enriched gap report flow.

Tests the full get_enriched_gaps() pipeline — from service calls through
enrichment to rendered output — using mocked external services.
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest

# The get_enriched_gaps() function lazily imports services.activity inside its
# body.  services.activity → notion.client → notion_client (external SDK).
# Mock notion_client at the module level so the import chain does not fail.
sys.modules["notion_client"] = MagicMock()

from services.gap_report import get_enriched_gaps


@pytest.mark.asyncio
async def test_full_flow_with_mocked_services():
    """Diet and journal services provide context; enrichment produces correct
    gap types and classifications with cross-log modifiers applied."""
    window_start = datetime(2026, 6, 8, 6, 0, tzinfo=timezone.utc)   # Monday 06:00 UTC
    window_end = datetime(2026, 6, 8, 23, 0, tzinfo=timezone.utc)     # Monday 23:00 UTC

    # Two activity entries with a 6 h gap between them (12:00 — 18:00)
    entries = [
        {
            "page_id": "entry_001",
            "start": datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
            "type": "work",
        },
        {
            "page_id": "entry_002",
            "start": datetime(2026, 6, 8, 18, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 6, 8, 20, 0, tzinfo=timezone.utc),
            "type": "work",
        },
    ]

    # Mock diet service returns a lunch entry during the gap
    diet_service = AsyncMock()
    diet_service.get_diet_entries.return_value = [
        {
            "meal_type": "Lunch",
            "description": "Salad and soup",
            "timestamp": "2026-06-08T13:30:00Z",
            "date": "2026-06-08",
            "page_id": "diet_001",
        },
    ]

    # Mock journal service returns a subjective entry for that day
    journal_service = AsyncMock()
    journal_service.get_entries.return_value = [
        {
            "type": "subjective",
            "date": "2026-06-08",
            "energy": 7,
            "focus": 8,
            "happiness": 6,
        },
    ]

    enriched = await get_enriched_gaps(
        entries,
        window_start=window_start,
        window_end=window_end,
        diet_service=diet_service,
        journal_service=journal_service,
    )

    # ── assertions ──────────────────────────────────────────────────────

    assert len(enriched) == 1, "Expected exactly one enriched gap"

    gap = enriched[0]

    # Gap boundaries
    assert gap.after_entry_id == "entry_001"
    assert gap.before_entry_id == "entry_002"
    assert gap.hours == 6.0

    # Classification — lunch entry in the middle → likely_mealtime
    assert gap.classification == "likely_mealtime", \
        f"Expected 'likely_mealtime', got '{gap.classification}'"

    # Severity — 6 h daytime on weekday with diet context
    #   duration 6 h → score 2; daytime +0.8; weekday +0.4; diet -0.8
    #   raw = 2 + 0.8 + 0.4 - 0.8 = 2.4 → medium
    assert gap.severity == "medium", \
        f"Expected 'medium', got '{gap.severity}'"

    # Cross-log reasons include the modifier
    reason_text = " ".join(gap.severity_reasons).lower()
    assert "cross-log" in reason_text, \
        "Severity reasons should mention cross-log context reduction"

    # Diet context captured
    assert len(gap.diet_during) == 1
    assert gap.diet_during[0]["meal_type"] == "Lunch"

    # Journal context captured
    assert gap.journal_day.get("energy") == 7

    # Services were actually called with expected arguments
    diet_service.get_diet_entries.assert_awaited_once()
    assert str(diet_service.get_diet_entries.await_args.kwargs["date_from"]) == "2026-06-08"
    assert str(diet_service.get_diet_entries.await_args.kwargs["date_to"]) == "2026-06-08"

    journal_service.get_entries.assert_awaited_once()


@pytest.mark.asyncio
async def test_graceful_degradation_with_empty_services():
    """When diet/journal services return empty data, the report still produces
    valid gaps based on time-of-day heuristics (e.g. sleep window detection)."""
    window_start = datetime(2026, 6, 8, 6, 0, tzinfo=timezone.utc)    # Monday 06:00 UTC
    window_end = datetime(2026, 6, 9, 10, 0, tzinfo=timezone.utc)     # Tuesday 10:00 UTC

    # Two entries with an 8 h overnight gap (23:00 — 07:00 next day)
    entries = [
        {
            "page_id": "entry_010",
            "start": datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 6, 8, 23, 0, tzinfo=timezone.utc),
            "type": "work",
        },
        {
            "page_id": "entry_011",
            "start": datetime(2026, 6, 9, 7, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc),
            "type": "morning_routine",
        },
    ]

    # Both services return empty data
    diet_service = AsyncMock()
    diet_service.get_diet_entries.return_value = []

    journal_service = AsyncMock()
    journal_service.get_entries.return_value = []

    enriched = await get_enriched_gaps(
        entries,
        window_start=window_start,
        window_end=window_end,
        diet_service=diet_service,
        journal_service=journal_service,
    )

    # ── assertions ──────────────────────────────────────────────────────

    assert len(enriched) == 1, "Expected exactly one enriched gap"

    gap = enriched[0]

    # Gap boundaries
    assert gap.after_entry_id == "entry_010"
    assert gap.before_entry_id == "entry_011"
    assert gap.hours == 8.0

    # Time-of-day heuristic: overnight gap 23:00—07:00 → likely_sleep
    assert gap.classification == "likely_sleep", \
        f"Expected 'likely_sleep' from time-of-day heuristic, got '{gap.classification}'"

    # Severity — 8 h overnight with sleep-window modifiers
    #   duration 8 h → score 2; sleep -1.2; weekday +0.4; cross-log(sleep) -2.0
    #   raw = 2 - 1.2 + 0.4 + 0 - 2.0 = -0.8 → clamped to 0 → info
    assert gap.severity in ("info", "low"), \
        f"Expected 'info' or 'low' for sleep-window gap, got '{gap.severity}'"

    # No external context
    assert gap.diet_during == [], \
        "Expected empty diet_during with no service data"
    assert gap.journal_day == {}, \
        "Expected empty journal_day with no service data"

    # Services were called (degradation means no crash, not skip)
    diet_service.get_diet_entries.assert_awaited_once()
    journal_service.get_entries.assert_awaited_once()
    assert str(diet_service.get_diet_entries.await_args.kwargs["date_from"]) == "2026-06-08"
    assert str(journal_service.get_entries.await_args.kwargs["date_from"]) == "2026-06-08"
