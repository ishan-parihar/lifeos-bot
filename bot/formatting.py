# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/formatting.py
"""
Telegram HTML formatting utilities.
All message rendering goes through this module for consistent formatting.
"""

from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional


def bold(text: str) -> str:
    return f"<b>{text}</b>"


def italic(text: str) -> str:
    return f"<i>{text}</i>"


def code(text: str) -> str:
    return f"<code>{text}</code>"


def pre(text: str) -> str:
    return f"<pre>{text}</pre>"


def link(text: str, url: str) -> str:
    return f'<a href="{url}">{text}</a>'


def bullet(text: str) -> str:
    return f"  • {text}"


def line_break() -> str:
    return "\n"


def separator() -> str:
    return "─" * 28


def fmt_dur(hours: float) -> str:
    """Format hours as 'Xh Ym'."""
    total_min = int(hours * 60)
    h, m = divmod(total_min, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def fmt_pct(value: float, total: float) -> str:
    """Format percentage."""
    if not total:
        return "0%"
    return f"{value / total * 100:.1f}%"


def fmt_time(dt: datetime) -> str:
    """Format datetime as HH:MM."""
    return dt.strftime("%H:%M")


def fmt_time_with_date(dt: datetime, reference: Optional[datetime] = None) -> str:
    """Format time, showing short date if different from reference day."""
    if reference and dt.date() == reference.date():
        return dt.strftime("%H:%M")
    return dt.strftime("%b %d %H:%M")


def fmt_date(dt: date) -> str:
    """Format date as 'Mon, May 29 2026'."""
    return dt.strftime("%a, %b %d %Y")


def fmt_time_range(start: datetime, end: datetime) -> str:
    """Format time range as 'HH:MM - HH:MM (Xh Ym)'."""
    dur_hrs = (end - start).total_seconds() / 3600
    return f"{fmt_time(start)} - {fmt_time(end)} ({fmt_dur(dur_hrs)})"


# ── Dashboard ────────────────────────────────────────────────────────────────

def render_dashboard(
    entries_48h: int, hrs_48h: float,
    entries_7d: int, hrs_7d: float,
    entries_30d: int, hrs_30d: float,
    category_breakdown: List[Tuple[str, float]],
) -> str:
    """Renders the activity dashboard as HTML."""
    total_48h, total_7d, total_30d = 48.0, 168.0, 720.0
    u48 = max(0, total_48h - hrs_48h)
    u7 = max(0, total_7d - hrs_7d)
    u30 = max(0, total_30d - hrs_30d)

    lines = [
        bold("Activity Log — Dashboard"),
        "",
        f"<b>48h</b>  {entries_48h} entries  |  {code(fmt_dur(hrs_48h))} tracked  |  {code(fmt_dur(u48))} untracked  ({fmt_pct(hrs_48h, total_48h)})",
        f"<b> 7d</b>  {entries_7d} entries  |  {code(fmt_dur(hrs_7d))} tracked  |  {code(fmt_dur(u7))} untracked  ({fmt_pct(hrs_7d, total_7d)})",
        f"<b>30d</b>  {entries_30d} entries  |  {code(fmt_dur(hrs_30d))} tracked  |  {code(fmt_dur(u30))} untracked  ({fmt_pct(hrs_30d, total_30d)})",
    ]

    if category_breakdown:
        lines.append("")
        lines.append(bold("Time by Category (7d)"))
        for cat, hrs in category_breakdown:
            lines.append(f"  {code(fmt_dur(hrs)):>14}  {cat}  ({fmt_pct(hrs, hrs_7d)})")

    return "\n".join(lines)


# ── Daily View ───────────────────────────────────────────────────────────────

# ── Entry Detail ─────────────────────────────────────────────────────────────

def render_entry_detail(entry: dict) -> str:
    """Renders a single entry's detail view."""
    start = entry.get("start")
    end = entry.get("end")
    title = entry.get("title", "")

    time_str = fmt_time_range(start, end) if start and end else ""

    lines = [
        bold("Entry"),
        f"{title}",
        f"{time_str}",
    ]

    return "\n".join(lines)


# ── Gap Report ───────────────────────────────────────────────────────────────

def render_gap_report(gaps: List[dict]) -> str:
    """Renders gap report as HTML."""
    if not gaps:
        return "No gaps >= 4h found in the last 7 days."

    lines = [bold(f"Gap Report — {len(gaps)} gap(s) >= 4h")]
    lines.append("")
    for g in gaps[:15]:
        if g.get("is_boundary"):
            lines.append(
                f"  <code>{g['start_date']} {g['start_time']}</code>"
                f" → <code>{g['end_date']} {g['end_time']}</code>"
                f"  ({fmt_dur(g['hours'])})"
            )
        else:
            lines.append(f"  <code>{g['date']}</code>  {g['start']}-{g['end']}  ({fmt_dur(g['hours'])})")
    if len(gaps) > 15:
        lines.append(f"  ... and {len(gaps) - 15} more")

    return "\n".join(lines)


# ── Telegram HTML escape ─────────────────────────────────────────────────────

def escape(text: str) -> str:
    """Escapes HTML special characters for Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Rolling 24h View ─────────────────────────────────────────────────────────

def find_duplicates_and_overlaps(entries: List[dict]) -> dict:
    """
    Finds duplicate and overlapping entries.
    Returns dict with 'duplicates' (list of entry indices) and 'overlaps' (list of (i, j) pairs).
    """
    duplicates = []
    overlaps = []

    # Check for exact duplicates (same start, end, type)
    seen = {}
    for i, e in enumerate(entries):
        key = (e.get("start"), e.get("end"), e.get("activity_type"))
        if key in seen:
            duplicates.append(i)
        else:
            seen[key] = i

    # Check for overlapping time ranges
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            s1, e1 = entries[i].get("start"), entries[i].get("end")
            s2, e2 = entries[j].get("start"), entries[j].get("end")
            if s1 and e1 and s2 and e2:
                # Overlap: start1 < end2 AND start2 < end1
                if s1 < e2 and s2 < e1:
                    overlaps.append((i, j))

    return {"duplicates": duplicates, "overlaps": overlaps}


def render_rolling_view(
    entries: List[dict],
    window_start: datetime,
    window_end: datetime,
    gaps: List[dict],
) -> str:
    """Renders entries in a rolling time window with duplicate/overlap flags.

    Gap dict formats supported:
    - ``after_entry_id``: rendered after the entry whose page_id matches
    - ``before_all``: rendered before all entries (boundary-start gap)
    - ``after_all``: rendered after all entries (boundary-end gap)
    """
    now = datetime.now(window_start.tzinfo) if window_start.tzinfo else datetime.now()
    start_str = fmt_time_with_date(window_start, now) if window_start.date() == window_end.date() else f"{window_start.strftime('%b %d')} {fmt_time(window_start)}"
    end_str = fmt_time_with_date(window_end, now) if window_start.date() == window_end.date() else f"{window_end.strftime('%b %d')} {fmt_time(window_end)}"

    lines = [
        bold(f"Activity Log — {start_str} → {end_str}"),
        "",
    ]

    # Separate boundary gaps from entry gaps
    before_gap = next((g for g in gaps if g.get("before_all")), None)
    after_gap = next((g for g in gaps if g.get("after_all")), None)

    # Detect duplicates and overlaps
    issues = find_duplicates_and_overlaps(entries)
    dup_set = set(issues["duplicates"])
    overlap_set = set()
    for i, j in issues["overlaps"]:
        overlap_set.add(i)
        overlap_set.add(j)

    # Before-entry boundary gap
    if before_gap:
        lines.append(f"  {separator()}")
        lines.append(f"  {bold('GAP')} {fmt_dur(before_gap['hours'])} ({before_gap['start']} → {before_gap['end']})")
        lines.append(f"  {separator()}")

    for idx, entry in enumerate(entries):
        start = entry.get("start")
        end = entry.get("end")
        title_full = entry.get("title", "") or entry.get("activity_type", "")
        dur = entry.get("duration_hrs", 0)

        time_str = ""
        if start:
            time_str = fmt_time_with_date(start, now)
        if end:
            time_str += f"-{fmt_time_with_date(end, now)}"

        # Flag issues
        flags = []
        if idx in dup_set:
            flags.append(bold("DUPLICATE"))
        if idx in overlap_set:
            flags.append(bold("OVERLAP"))
        flag_str = f"  {' '.join(flags)}" if flags else ""

        lines.append(f"  <code>{time_str:>15}</code>  {title_full}  ({fmt_dur(dur)}){flag_str}")

        for gap in gaps:
            if gap.get("after_entry_id") == entry.get("page_id"):
                lines.append(f"  {separator()}")
                lines.append(f"  {bold('GAP')} {fmt_dur(gap['hours'])} ({gap['start']} → {gap['end']})")
                lines.append(f"  {separator()}")

    # After-entry boundary gap
    if after_gap:
        lines.append(f"  {separator()}")
        lines.append(f"  {bold('GAP')} {fmt_dur(after_gap['hours'])} ({after_gap['start']} → {after_gap['end']})")
        lines.append(f"  {separator()}")

    total_hrs = sum(e.get("duration_hrs", 0) for e in entries)
    lines.append("")
    lines.append(f"<b>Total:</b> {fmt_dur(total_hrs)} | {len(entries)} entries")

    if issues["duplicates"] or issues["overlaps"]:
        lines.append("")
        lines.append(bold("Issues:"))
        if issues["duplicates"]:
            lines.append(f"  {len(issues['duplicates'])} duplicate(s) detected")
        if issues["overlaps"]:
            lines.append(f"  {len(issues['overlaps'])} overlap(s) detected")

    return "\n".join(lines)


# ── Entry Flow Timeline with Marker ──────────────────────────────────────────

def render_timeline_with_marker(
    entries: List[dict],
    marker_start: datetime,
    marker_end: datetime,
    marker_title: str,
) -> str:
    """
    Shows +/- 24h entries with a visual marker at the insertion point.
    Used during entry flow to show where the new entry will go.
    """
    now = datetime.now(marker_start.tzinfo) if marker_start.tzinfo else datetime.now()
    marker_dur = (marker_end - marker_start).total_seconds() / 3600
    lines = [f"<i>Timeline context</i>"]
    lines.append("")

    inserted = False
    for entry in entries:
        start = entry.get("start")
        end = entry.get("end")
        title_full = entry.get("title", "") or entry.get("activity_type", "")
        dur = entry.get("duration_hrs", 0)

        # Insert marker before this entry if it starts after marker_start
        if not inserted and start and start >= marker_start:
            lines.append(f"  {bold('▼')} <code>{fmt_time_with_date(marker_start, now):>15}</code>  {bold(marker_title)}  ({fmt_dur(marker_dur)})")
            lines.append(f"  {'─' * 30}")
            inserted = True

        time_str = ""
        if start:
            time_str = fmt_time_with_date(start, now)
        if end:
            time_str += f"-{fmt_time_with_date(end, now)}"

        lines.append(f"  <code>{time_str:>15}</code>  {title_full}  ({fmt_dur(dur)})")

    # If marker wasn't inserted (it goes after all entries)
    if not inserted:
        lines.append(f"  {bold('▼')} <code>{fmt_time(marker_start):>11}</code>  {bold(marker_title)}  ({fmt_dur(marker_dur)})")
        lines.append(f"  {'─' * 30}")

    return "\n".join(lines)


def render_mini_timeline(entries: List[dict], label: str = "Last 24h") -> str:
    """
    Compact timeline of recent entries for context during logging.
    Shows entries as a vertical list with gap markers.
    """
    if not entries:
        return f"<i>{label}: no entries</i>"

    now = datetime.now(entries[0]["start"].tzinfo) if entries and entries[0].get("start") else datetime.now()
    lines = [f"<i>{label}</i>"]
    for i, entry in enumerate(entries):
        start = entry.get("start")
        end = entry.get("end")
        title_full = entry.get("title", "") or entry.get("activity_type", "")
        dur = entry.get("duration_hrs", 0)

        time_str = ""
        if start:
            time_str = fmt_time_with_date(start, now)
        if end:
            time_str += f"-{fmt_time_with_date(end, now)}"

        lines.append(f"  <code>{time_str:>15}</code> {title_full} ({fmt_dur(dur)})")

        # Gap marker
        if i < len(entries) - 1:
            next_start = entries[i + 1].get("start")
            if end and next_start:
                gap_hrs = (next_start - end).total_seconds() / 3600
                if gap_hrs >= 0.5:
                    gap_start = fmt_time_with_date(end, now)
                    gap_end = fmt_time_with_date(next_start, now)
                    lines.append(f"  <code>{'':>15}</code> <b>GAP</b> {fmt_dur(gap_hrs)} ({gap_start}-{gap_end})")

    return "\n".join(lines)
