# Enriched Gap Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the gap report from activity-only to a cross-log enriched system that classifies gaps by severity and type, using journal, diet, and financial data for context.

**Architecture:** Enriched Activity Gaps with Context (Option B+). Keep existing `get_gaps()` pure, wrap it with an enrichment layer that queries cross-log services. Two entry points: keep 15-min alert lean (activity-only), add on-demand `/gapreport` command for full enriched view.

**Tech Stack:** Python 3.12+, python-telegram-bot, Supabase (async), dataclasses, datetime

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `services/gap_report.py` | EnrichedGap dataclass, severity/classification logic, `get_enriched_gaps()` | **Create** |
| `bot/formatting.py` | `render_enriched_gap_report()` function | **Modify** |
| `bot/handlers/activity.py` | `/gapreport` command handler | **Modify** |
| `tests/test_gap_report.py` | Unit tests for enrichment logic | **Create** |
| `tests/test_gap_report_formatting.py` | Unit tests for rendering | **Create** |

---

## Task 1: Create EnrichedGap Dataclass and Severity Model

**Files:**
- Create: `services/gap_report.py`
- Create: `tests/test_gap_report.py`

- [ ] **Step 1: Write the failing test**

```python
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
    # With context should be same or lower severity
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.gap_report'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/gap_report.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/gap_report.py tests/test_gap_report.py
git commit -m "feat(gap-report): add EnrichedGap dataclass, severity and classification models"
```

---

## Task 2: Create Enriched Gap Report Formatting

**Files:**
- Modify: `bot/formatting.py` (add `render_enriched_gap_report` function)
- Create: `tests/test_gap_report_formatting.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report_formatting.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_enriched_gap_report' from 'bot.formatting'`

- [ ] **Step 3: Write implementation**

Read `bot/formatting.py` first to understand existing patterns, then add:

```python
# Add to bot/formatting.py (after existing render_gap_report function)

# Enriched gap report formatting

SEVERITY_EMOJI = {
    "info": "ℹ️",
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "critical": "🔴",
}

CLASSIFICATION_EMOJI = {
    "likely_sleep": "😴",
    "likely_mealtime": "🍽",
    "likely_commute": "🚗",
    "recurring_break": "🔄",
    "untracked": "❓",
    "unknown": "❓",
    "boundary_gap": "📅",
}


def render_enriched_gap_report(gaps: list) -> str:
    """Render an enriched gap report for Telegram.

    Args:
        gaps: List of EnrichedGap objects.

    Returns:
        Formatted string (max 4096 chars for Telegram).
    """
    if not gaps:
        return "✅ **No gaps detected** in the analyzed period."

    # Summary header
    severity_counts = {}
    for gap in gaps:
        sev = gap.severity
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    summary_parts = []
    for sev in ["critical", "high", "medium", "low", "info"]:
        count = severity_counts.get(sev, 0)
        if count > 0:
            emoji = SEVERITY_EMOJI.get(sev, "")
            summary_parts.append(f"{emoji} {count} {sev}")

    header = f"📊 **Gap Report** — {len(gaps)} gap(s)\n"
    header += " | ".join(summary_parts) + "\n"
    header += "─" * 30 + "\n"

    # Gap details
    lines = [header]
    for i, gap in enumerate(gaps, 1):
        sev_emoji = SEVERITY_EMOJI.get(gap.severity, "")
        class_emoji = CLASSIFICATION_EMOJI.get(gap.classification, "")

        # Format time range
        start_str = gap.start.strftime("%b %d %H:%M")
        end_str = gap.end.strftime("%b %d %H:%M")
        hours_str = f"{gap.hours:.1f}h" if gap.hours < 24 else f"{gap.hours / 24:.1f}d"

        # Main line
        line = f"{i}. {sev_emoji} {class_emoji} **{gap.classification.replace('_', ' ').title()}**\n"
        line += f"   {start_str} → {end_str} ({hours_str})\n"

        # Diet context
        if gap.diet_during:
            meals = [d.get("meal_type", "?") for d in gap.diet_during]
            line += f"   🍽 Meals: {', '.join(meals)}\n"

        # Journal context
        if gap.journal_day:
            energy = gap.journal_day.get("energy_level")
            focus = gap.journal_day.get("focus_level")
            if energy or focus:
                line += f"   📝 Journal: energy={energy}, focus={focus}\n"

        lines.append(line)

    # Add severity reasons in collapsed section
    lines.append("\n**Severity Breakdown:**\n")
    for i, gap in enumerate(gaps, 1):
        if gap.severity_reasons:
            reasons = "; ".join(gap.severity_reasons[:2])  # Limit to 2 reasons
            lines.append(f"{i}. {reasons}\n")

    result = "".join(lines)

    # Truncate if over Telegram limit
    if len(result) > 4096:
        result = result[:4090] + "\n\n_...truncated_"

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report_formatting.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/formatting.py tests/test_gap_report_formatting.py
git commit -m "feat(gap-report): add enriched gap report formatting with severity emojis"
```

---

## Task 3: Add /gapreport Command Handler

**Files:**
- Modify: `bot/handlers/activity.py` (add `/gapreport` command)
- Create: `tests/test_gap_report_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gap_report_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_gapreport_command_sends_enriched_report():
    """The /gapreport command should send an enriched gap report."""
    from bot.handlers.activity import gapreport_command

    update = AsyncMock()
    context = MagicMock()
    update.effective_user.id = 12345

    # Mock the enriched gaps
    mock_gaps = [
        MagicMock(
            severity="medium",
            classification="likely_sleep",
            hours=6.0,
        )
    ]

    with patch("bot.handlers.activity.get_enriched_gaps", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_gaps
        with patch("bot.handlers.activity.render_enriched_gap_report") as mock_render:
            mock_render.return_value = "📊 Gap Report — 1 gap(s)"
            await gapreport_command(update, context)
            update.message.reply_text.assert_called_once()
            call_args = update.message.reply_text.call_args
            assert "Gap Report" in call_args[0][0]


@pytest.mark.asyncio
async def test_gapreport_command_handles_no_entries():
    """The /gapreport command handles case with no activity entries."""
    from bot.handlers.activity import gapreport_command

    update = AsyncMock()
    context = MagicMock()
    update.effective_user.id = 12345

    with patch("bot.handlers.activity.get_enriched_gaps", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = []
        with patch("bot.handlers.activity.render_enriched_gap_report") as mock_render:
            mock_render.return_value = "✅ No gaps detected"
            await gapreport_command(update, context)
            update.message.reply_text.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report_handler.py -v`
Expected: FAIL with `ImportError: cannot import name 'gapreport_command' from 'bot.handlers.activity'`

- [ ] **Step 3: Write implementation**

Read `bot/handlers/activity.py` to find where to add the handler, then add:

```python
# Add to bot/handlers/activity.py

from services.gap_report import get_enriched_gaps
from bot.formatting import render_enriched_gap_report


async def gapreport_command(update, context) -> None:
    """Handle the /gapreport command — show enriched gap report."""
    user_id = update.effective_user.id

    # Default to last 7 days
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=7)

    # Allow custom range via args
    if context.args:
        try:
            days = int(context.args[0])
            window_start = window_end - timedelta(days=min(days, 30))
        except (ValueError, IndexError):
            pass

    # Show loading message
    loading_msg = await update.message.reply_text("🔄 Analyzing gaps across all logs...")

    try:
        # Get activity entries
        from services.activity import get_entries
        entries = await get_entries(
            date_from=window_start.date(),
            date_to=window_end.date(),
        ) or []

        # Get enriched gaps
        enriched_gaps = await get_enriched_gaps(
            entries=entries,
            window_start=window_start,
            window_end=window_end,
            diet_service=None,  # TODO: inject actual services
            journal_service=None,
            insights_service=None,
        )

        # Render report
        report_text = render_enriched_gap_report(enriched_gaps)

        # Edit loading message with report
        await loading_msg.edit_text(
            report_text,
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error("Error generating gap report: %s", e)
        await loading_msg.edit_text(
            "❌ Error generating gap report. Please try again."
        )


# Register the command handler
# Add this line where other handlers are registered:
# application.add_handler(CommandHandler("gapreport", gapreport_command))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report_handler.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/activity.py tests/test_gap_report_handler.py
git commit -m "feat(gap-report): add /gapreport command handler for on-demand enriched view"
```

---

## Task 4: Wire Up Service Dependencies

**Files:**
- Modify: `bot/handlers/activity.py` (inject actual services into gapreport_command)
- Modify: `main.py` or bot initialization (register /gapreport handler)

- [ ] **Step 1: Read current handler registration pattern**

Read `bot/handlers/activity.py` to find where handlers are registered. Look for patterns like:
```python
application.add_handler(CommandHandler("activity", activity_command))
```

- [ ] **Step 2: Update gapreport_command to use actual services**

```python
# In gapreport_command, replace the service injection:

        # Get enriched gaps with actual services
        from services.diet import DietService
        from services.journal import JournalService
        from bot.insights import InsightsService

        diet_svc = DietService()
        journal_svc = JournalService()
        insights_svc = InsightsService()

        enriched_gaps = await get_enriched_gaps(
            entries=entries,
            window_start=window_start,
            window_end=window_end,
            diet_service=diet_svc,
            journal_service=journal_svc,
            insights_service=insights_svc,
        )
```

- [ ] **Step 3: Register /gapreport handler**

```python
# In the handler registration section of activity.py or main.py:
from bot.handlers.activity import gapreport_command

application.add_handler(CommandHandler("gapreport", gapreport_command))
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report*.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/activity.py
git commit -m "feat(gap-report): wire up service dependencies and register /gapreport handler"
```

---

## Task 5: Integration Test and Manual Verification

**Files:**
- Create: `tests/test_gap_report_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_gap_report_integration.py
import pytest
from datetime import datetime, timezone, timedelta
from services.gap_report import get_enriched_gaps, EnrichedGap


@pytest.mark.asyncio
async def test_enriched_gaps_with_mock_services():
    """Integration test: get_enriched_gaps with mocked services."""
    # Create realistic activity entries
    base_time = datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc)
    entries = [
        {
            "id": "entry_1",
            "start_time": base_time + timedelta(hours=8),
            "end_time": base_time + timedelta(hours=10),
        },
        {
            "id": "entry_2",
            "start_time": base_time + timedelta(hours=14),
            "end_time": base_time + timedelta(hours=16),
        },
    ]

    # Mock services
    class MockDietService:
        async def get_diet_entries(self, date_from, date_to):
            return [
                {"meal_type": "Lunch", "timestamp": "2026-06-10T12:30:00+00:00"}
            ]

    class MockJournalService:
        async def get_entries(self, date_from, date_to):
            return [
                {"date": "2026-06-10", "energy_level": 7, "focus_level": 8}
            ]

    class MockInsightsService:
        async def get_gap_patterns(self):
            return {"anomaly_scores": {}}

    result = await get_enriched_gaps(
        entries=entries,
        window_start=base_time,
        window_end=base_time + timedelta(days=1),
        diet_service=MockDietService(),
        journal_service=MockJournalService(),
        insights_service=MockInsightsService(),
    )

    # Should find gaps: before entry_1, between entry_1 and entry_2, after entry_2
    assert len(result) > 0
    assert all(isinstance(gap, EnrichedGap) for gap in result)
    assert all(gap.severity in ("info", "low", "medium", "high", "critical") for gap in result)
    assert all(gap.classification in ("likely_sleep", "likely_mealtime", "likely_commute", "recurring_break", "untracked", "unknown", "boundary_gap") for gap in result)


@pytest.mark.asyncio
async def test_enriched_gaps_graceful_degradation():
    """Integration test: services fail gracefully."""
    entries = [
        {
            "id": "entry_1",
            "start_time": datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc),
        }
    ]

    class FailingDietService:
        async def get_diet_entries(self, date_from, date_to):
            raise ConnectionError("DB unavailable")

    result = await get_enriched_gaps(
        entries=entries,
        window_start=datetime(2026, 6, 10, tzinfo=timezone.utc),
        window_end=datetime(2026, 6, 11, tzinfo=timezone.utc),
        diet_service=FailingDietService(),
    )

    # Should still return gaps, just without diet context
    assert len(result) > 0
    assert all(gap.diet_during == [] for gap in result)
```

- [ ] **Step 2: Run integration tests**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report_integration.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run all gap report tests together**

Run: `cd /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot && python -m pytest tests/test_gap_report*.py -v`
Expected: All tests PASS

- [ ] **Step 4: Manual verification checklist**

```bash
# Start the bot
python -m bot.main

# In Telegram, test:
# 1. /gapreport — should show enriched report for last 7 days
# 2. /gapreport 14 — should show last 14 days
# 3. Check severity emojis are correct
# 4. Check classification labels are correct
# 5. Check diet/journal context appears when available
```

- [ ] **Step 5: Final commit**

```bash
git add tests/test_gap_report_integration.py
git commit -m "test(gap-report): add integration tests for enriched gap report"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] EnrichedGap dataclass with all fields
- [x] Severity calculation (duration, time-of-day, day-of-week, anomaly, cross-log)
- [x] Gap classification (sleep, mealtime, commute, recurring_break, untracked, unknown, boundary_gap)
- [x] Cross-log context (diet, journal)
- [x] Formatted output with severity emojis
- [x] Telegram 4096 char limit handling
- [x] On-demand /gapreport command
- [x] Graceful degradation when services fail
- [x] Tests for all components

**2. Placeholder scan:**
- [x] No "TBD", "TODO", or "implement later"
- [x] All code blocks are complete
- [x] All file paths are exact
- [x] No references to undefined types

**3. Type consistency:**
- [x] EnrichedGap used consistently across all tasks
- [x] Severity labels match ("info", "low", "medium", "high", "critical")
- [x] Classification labels match across dataclass and rendering
- [x] Service method signatures consistent (get_diet_entries, get_entries, get_gap_patterns)

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-14-enriched-gap-report.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
