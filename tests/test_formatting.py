"""Unit tests for the Telegram HTML formatting layer (bot/formatting.py).

These cover the pure rendering helpers only — no Notion or Telegram I/O —
so they pin message formatting without any external service.
"""
from datetime import date, datetime, timedelta, timezone

from bot.formatting import (
    bold,
    italic,
    code,
    pre,
    link,
    bullet,
    separator,
    escape,
    fmt_dur,
    fmt_pct,
    fmt_time,
    fmt_time_with_date,
    fmt_date,
    fmt_time_range,
    find_duplicates_and_overlaps,
    render_dashboard,
    render_rolling_view,
)


def test_inline_formatting_tags():
    assert bold("x") == "<b>x</b>"
    assert italic("x") == "<i>x</i>"
    assert code("x") == "<code>x</code>"
    assert pre("x") == "<pre>x</pre>"
    assert link("t", "https://u") == '<a href="https://u">t</a>'


def test_bullet_and_separator_shapes():
    assert bullet("t") == "  • t"
    assert separator() == "─" * 28


def test_escape_handles_html_specials():
    assert escape("a&b<c>d") == "a&amp;b&lt;c&gt;d"


def test_fmt_dur_minutes_only():
    assert fmt_dur(0.5) == "30m"
    assert fmt_dur(0.25) == "15m"
    assert fmt_dur(0) == "0m"


def test_fmt_dur_hours_and_minutes():
    assert fmt_dur(2) == "2h"
    assert fmt_dur(1.5) == "1h 30m"


def test_fmt_pct():
    assert fmt_pct(25, 100) == "25.0%"
    assert fmt_pct(5, 0) == "0%"  # division by zero guard


def test_fmt_time():
    dt = datetime(2026, 1, 1, 9, 30)
    assert fmt_time(dt) == "09:30"


def test_fmt_time_with_date_same_day_omits_date():
    ref = datetime(2026, 1, 1, 8, 0)
    dt = datetime(2026, 1, 1, 9, 30)
    assert fmt_time_with_date(dt, ref) == "09:30"


def test_fmt_time_with_date_other_day_shows_short_date():
    ref = datetime(2026, 1, 1, 8, 0)
    dt = datetime(2026, 1, 2, 9, 30)
    assert fmt_time_with_date(dt, ref) == "Jan 02 09:30"


def test_fmt_date():
    assert fmt_date(date(2026, 1, 1)) == "Thu, Jan 01 2026"


def test_fmt_time_range():
    start = datetime(2026, 1, 1, 9, 30)
    end = datetime(2026, 1, 1, 11, 30)
    assert fmt_time_range(start, end) == "09:30 - 11:30 (2h)"


def _entry(start_h, end_h, title, start_d=1):
    return {
        "start": datetime(2026, 1, start_d, start_h, 0),
        "end": datetime(2026, 1, start_d, end_h, 0),
        "activity_type": "focus",
        "title": title,
        "duration_hrs": end_h - start_h,
        "page_id": f"e{start_h}",
    }


def test_find_duplicates_and_overlaps_clean():
    entries = [_entry(9, 10, "a"), _entry(10, 11, "b")]
    issues = find_duplicates_and_overlaps(entries)
    assert issues == {"duplicates": [], "overlaps": []}


def test_find_duplicates_and_overlaps_flags_duplicates():
    # Two identical entries are flagged as duplicates AND as overlapping.
    entries = [_entry(9, 10, "a"), _entry(9, 10, "a")]
    issues = find_duplicates_and_overlaps(entries)
    assert issues["duplicates"] == [1]
    assert issues["overlaps"] == [(0, 1)]


def test_find_duplicates_and_overlaps_flags_overlaps():
    # 09:00-10:00 overlaps 09:30-10:30
    first = _entry(9, 10, "a")
    second = {
        **first,
        "start": datetime(2026, 1, 1, 9, 30),
        "end": datetime(2026, 1, 1, 10, 30),
        "title": "b",
    }
    issues = find_duplicates_and_overlaps([first, second])
    assert issues["overlaps"] == [(0, 1)]
    assert issues["duplicates"] == []


def test_render_dashboard_shows_counts_and_totals():
    out = render_dashboard(
        entries_48h=10, hrs_48h=20.0,
        entries_7d=70, hrs_7d=140.0,
        entries_30d=300, hrs_30d=600.0,
        category_breakdown=[("Work", 3.5)],
    )
    assert "Activity Log — Dashboard" in out
    assert "10 entries" in out
    assert "41.7%" in out  # 20/48 tracked
    assert "Work" in out


def test_render_rolling_view_lists_entries_and_total():
    entries = [_entry(9, 10, "Morning focus"), _entry(11, 12, "Deep work")]
    out = render_rolling_view(
        entries,
        window_start=datetime(2026, 1, 1, 0, 0),
        window_end=datetime(2026, 1, 1, 23, 59),
        gaps=[],
    )
    assert "Morning focus" in out
    assert "Deep work" in out
    assert "Total:" in out
    assert "2h" in out
