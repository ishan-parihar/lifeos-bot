# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/services/activity.py
"""
Activity log service layer.

Pure business logic for activity entry CRUD, stats, gap detection, and time utilities.
No Telegram dependencies — consumes NotionClientManager and returns structured dicts.
Both the Telegram bot and CLI simulator consume these services.
"""

import logging
from datetime import datetime, timedelta, timezone, date, time
from typing import Dict, Any, List, Optional

from config import settings
from notion.client import notion_manager
from notion.models import NotionPayloadBuilder as NB

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=5, minutes=30))  # IST


# ── Time Helpers ──────────────────────────────────────────────────────────────


def round_to_15(dt: datetime) -> datetime:
    """Rounds a datetime to the nearest 15-minute interval."""
    minutes = dt.minute
    rounded = (minutes + 7) // 15 * 15
    if rounded == 60:
        dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        dt = dt.replace(minute=rounded, second=0, microsecond=0)
    return dt


def hhmm_to_dt(hhmm: str, base_date: date) -> datetime:
    """Converts HHMM string to a timezone-aware datetime on base_date."""
    h, m = int(hhmm[:2]), int(hhmm[2:])
    return datetime(base_date.year, base_date.month, base_date.day, h, m, tzinfo=TZ)


def dt_to_hhmm(dt: datetime) -> str:
    """Formats a datetime as HHMM string."""
    return dt.strftime("%H%M")


def parse_compact_dt(compact: str) -> datetime:
    """Parses compact ISO datetime (YYYYMMDDTHHMM) to timezone-aware datetime."""
    dt = datetime.strptime(compact, "%Y%m%dT%H%M")
    return dt.replace(tzinfo=TZ)


def fmt_time_with_date(dt: datetime, reference: Optional[datetime] = None) -> str:
    """Formats time, showing short date if different from reference day.

    Example: "14:30" if same day, "Jun 12 14:30" if different day.
    """
    if reference and dt.date() == reference.date():
        return dt.strftime("%H:%M")
    return dt.strftime("%b %d %H:%M")


# ── Save / Create ─────────────────────────────────────────────────────────────


async def save_activity_entry(
    activity_type: str,
    start: datetime,
    end: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates an activity entry in Notion and handles eventual consistency.

    Builds the Notion page properties from the provided fields, creates the page,
    then re-queries entries around the entry date to confirm the save. If Notion
    hasn't indexed the new page yet (eventual consistency delay), a synthetic
    entry is constructed in-memory.

    Args:
        activity_type: The type of activity (e.g. "Work", "Sleep").
        start: Start datetime (timezone-aware, IST).
        end: End datetime (timezone-aware, IST). Defaults to start + 1h.
        notes: Optional description text appended to the title.

    Returns:
        A dict with keys:
            - success (bool): Whether the operation succeeded.
            - page_id (str): The Notion page ID of the saved entry.
            - entry (dict): The saved entry (real or synthetic).
            - synthetic (bool): True if entry was injected due to eventual consistency.
            - surrounding_entries (list[dict]): Entries around the saved one.
            - window_start (datetime): Query window start.
            - window_end (datetime): Query window end.
            - error (str | None): Error message if success is False.
    """
    if end is None:
        end = start + timedelta(hours=1)

    title = f"{activity_type} - {notes}" if notes else activity_type
    dur_hrs = (end - start).total_seconds() / 3600

    logger.info("Saving activity: title=%s, start=%s, end=%s", title, start, end)

    properties = {
        "Name": NB.title(title),
        "Date": NB.date(start.isoformat(), end_iso=end.isoformat()),
    }

    try:
        result = await notion_manager.create_page(
            settings.DATABASE_ID_ACTIVITY_LOG, properties
        )
        new_page_id = result.get("id", "")
        logger.info("Activity saved: %s (page_id=%s)", title, new_page_id)

        # ── Re-query entries around the entry's date ──
        entry_date = start.date()
        window_start = datetime.combine(
            entry_date - timedelta(days=1), datetime.min.time(), tzinfo=TZ
        )
        window_end = datetime.combine(
            entry_date + timedelta(days=2), datetime.min.time(), tzinfo=TZ
        )
        start_str = window_start.date().isoformat()
        end_str = window_end.date().isoformat()
        fresh_entries = await notion_manager.query_activity_entries(
            start_str, end_str, sort_ascending=False
        )
        fresh_entries = [
            e
            for e in fresh_entries
            if e.get("start") and e["start"] >= window_start and e["start"] < window_end
        ]
        fresh_entries.sort(key=lambda e: e.get("start", datetime.min))

        # Try to locate the newly saved entry by page_id
        synthetic = False
        saved_idx = None
        entry = None
        for i, e in enumerate(fresh_entries):
            if new_page_id and e.get("page_id") == new_page_id:
                saved_idx = i
                entry = e
                break

        if saved_idx is None:
            logger.warning(
                "Entry (page_id=%s, start=%s) not found in fresh query — "
                "Notion eventual consistency; injecting synthetic entry",
                new_page_id,
                start,
            )
            entry = {
                "id": "",
                "page_id": new_page_id,
                "title": title,
                "activity_type": activity_type,
                "start": start,
                "end": end,
                "duration_hrs": dur_hrs,
            }
            # Insert at correct sorted position (fresh_entries is sorted ascending)
            insert_idx = len(fresh_entries)
            for i, e in enumerate(fresh_entries):
                e_start = e.get("start")
                if e_start and e_start <= start:
                    insert_idx = i + 1
                elif e_start and e_start > start:
                    insert_idx = i
                    break
            fresh_entries.insert(insert_idx, entry)
            saved_idx = insert_idx
            synthetic = True
            logger.info(
                "Injected synthetic entry at position %d/%d",
                insert_idx,
                len(fresh_entries),
            )

        # Extract surrounding entries for display context
        if saved_idx is not None:
            show_start = max(0, saved_idx - 10)
            show_end = min(len(fresh_entries), saved_idx + 11)
            surrounding_entries = fresh_entries[show_start:show_end]
        else:
            surrounding_entries = fresh_entries[-21:]

        return {
            "success": True,
            "page_id": new_page_id,
            "entry": entry,
            "synthetic": synthetic,
            "surrounding_entries": surrounding_entries,
            "all_entries": fresh_entries,
            "window_start": window_start,
            "window_end": window_end,
            "error": None,
        }

    except Exception as e:
        logger.error("Failed to save activity: %s", e, exc_info=True)
        return {
            "success": False,
            "page_id": "",
            "entry": None,
            "synthetic": False,
            "surrounding_entries": [],
            "window_start": None,
            "window_end": None,
            "error": str(e),
        }


# ── Query / Read ──────────────────────────────────────────────────────────────


async def get_activity_entries(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    sort_ascending: bool = True,
    local_dates: bool = True,
) -> List[Dict[str, Any]]:
    """Queries activity entries from Notion within a date range.

    Args:
        date_from: ISO date string (YYYY-MM-DD or ISO datetime) for range start.
            Defaults to 30 days ago.
        date_to: ISO date string for range end. Defaults to tomorrow.
        limit: Maximum number of entries to return (max 100 in Notion query).
        sort_ascending: Sort chronologically (True) or newest-first (False).
        local_dates: If True, converts date strings to UTC range for IST offset.

    Returns:
        List of parsed entry dicts sorted by start time. Each entry has keys:
            page_id, title, activity_type, start (datetime), end (datetime),
            duration_hrs (float).
    """
    now = datetime.now(TZ)
    if not date_from:
        date_from = (now - timedelta(days=30)).date().isoformat()
    if not date_to:
        date_to = (now + timedelta(days=1)).date().isoformat()

    try:
        entries = await notion_manager.query_activity_entries(
            date_from,
            date_to,
            page_size=limit,
            sort_ascending=sort_ascending,
            local_dates=local_dates,
        )
        return entries
    except Exception as e:
        logger.error("Failed to query activity entries: %s", e, exc_info=True)
        return []


async def get_entry_detail(page_id: str) -> Dict[str, Any]:
    """Retrieves a single activity entry by page_id.

    Searches recent entries (last 30 days) for the matching page_id.

    Args:
        page_id: The Notion page ID of the entry.

    Returns:
        A dict with keys:
            - found (bool): Whether the entry was located.
            - entry (dict | None): The parsed entry data if found.
            - error (str | None): Error message if the lookup failed.
    """
    if not page_id:
        return {"found": False, "entry": None, "error": "No page_id provided"}

    try:
        now = datetime.now(TZ)
        month_ago = (now - timedelta(days=30)).isoformat()
        tomorrow = (now + timedelta(days=1)).isoformat()
        all_entries = await notion_manager.query_activity_entries(
            month_ago, tomorrow, sort_ascending=False
        )
        for e in all_entries:
            if e.get("page_id") == page_id:
                return {"found": True, "entry": e, "error": None}

        return {"found": False, "entry": None, "error": "Entry not found"}
    except Exception as e:
        logger.error("Failed to fetch entry %s: %s", page_id, e, exc_info=True)
        return {"found": False, "entry": None, "error": str(e)}


# ── Activity Types ────────────────────────────────────────────────────────────


async def get_activity_types() -> List[str]:
    """Fetches activity type options from the Notion select property.

    Returns a list of type name strings (e.g. ["Work", "Sleep", "Trading", ...]).
    Falls back to a reasonable default list if the Notion fetch fails.
    """
    try:
        types = await notion_manager.get_activity_types()
        if types:
            return [t["name"] for t in types]
    except Exception as e:
        logger.warning("Failed to fetch activity types: %s", e)

    # Fallback defaults
    return [
        "Work",
        "Workout",
        "Shadow Work",
        "Trading",
        "Networking",
        "Meeting",
        "Meditation",
        "Brain Games",
        "Sleep",
        "Chores",
        "Recreation",
        "Study",
        "Socialize",
        "Content Creation",
    ]


# ── Stats ─────────────────────────────────────────────────────────────────────


async def get_activity_stats(
    hours: int = 48,
) -> Dict[str, Any]:
    """Computes activity statistics for 48h, 7d, and 30d windows.

    Fetches 30 days of entries, then calculates per-window totals and a
    per-category breakdown for the 7-day window.

    Args:
        hours: Size of the "recent" window in hours (default 48).

    Returns:
        A dict with keys:
            - count_48h (int): Entry count in 48h window.
            - total_48h (float): Total hours tracked in 48h window.
            - count_7d (int): Entry count in 7d window.
            - total_7d (float): Total hours tracked in 7d window.
            - count_30d (int): Entry count in 30d window.
            - total_30d (float): Total hours tracked in 30d window.
            - category_breakdown (list[tuple[str, float]]): Per-type hours in 7d,
              sorted descending by hours.
            - error (str | None): Error message if the query failed.
    """
    now = datetime.now(TZ)
    today = now.date()

    try:
        month_ago = (today - timedelta(days=30)).isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        all_entries = await notion_manager.query_activity_entries(
            month_ago, tomorrow, sort_ascending=False
        )
        all_entries.sort(key=lambda e: e.get("start", datetime.min))
    except Exception as e:
        logger.error("Failed to fetch entries for stats: %s", e, exc_info=True)
        return {
            "count_48h": 0,
            "total_48h": 0.0,
            "count_7d": 0,
            "total_7d": 0.0,
            "count_30d": 0,
            "total_30d": 0.0,
            "category_breakdown": [],
            "error": str(e),
        }

    # Define time windows with overlap detection
    h48_start = now - timedelta(hours=48)
    d7_start = datetime.combine(
        today - timedelta(days=7), datetime.min.time(), tzinfo=TZ
    )

    def overlaps(entry, window_start, window_end):
        s = entry.get("start")
        e = entry.get("end")
        if not s:
            return False
        e = e or now
        return s < window_end and e > window_start

    entries_48h = [e for e in all_entries if overlaps(e, h48_start, now)]
    entries_7d = [e for e in all_entries if overlaps(e, d7_start, now)]
    entries_30d = all_entries

    def total_hours(entries):
        return sum(e.get("duration_hrs", 0) for e in entries)

    count_48h = len(entries_48h)
    total_48h = total_hours(entries_48h)
    count_7d = len(entries_7d)
    total_7d = total_hours(entries_7d)
    count_30d = len(entries_30d)
    total_30d = total_hours(entries_30d)

    # Category breakdown for 7d
    cat_hours: Dict[str, float] = {}
    for e in entries_7d:
        cat = e.get("activity_type", "Other") or "Other"
        cat_hours[cat] = cat_hours.get(cat, 0) + e.get("duration_hrs", 0)
    category_breakdown = sorted(cat_hours.items(), key=lambda x: -x[1])

    return {
        "count_48h": count_48h,
        "total_48h": round(total_48h, 2),
        "count_7d": count_7d,
        "total_7d": round(total_7d, 2),
        "count_30d": count_30d,
        "total_30d": round(total_30d, 2),
        "category_breakdown": category_breakdown,
        "error": None,
    }


# ── Gap Detection ─────────────────────────────────────────────────────────────


def get_gaps(
    entries: List[Dict[str, Any]],
    threshold_minutes: int = 30,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Detects gaps between consecutive activity entries.

    Entries must be sorted chronologically (ascending by start time).
    Only entries with both start and end times are considered.

    Args:
        entries: Chronologically sorted list of entry dicts. Each must have
            start (datetime), end (datetime), page_id (str).
        threshold_minutes: Minimum gap duration to report (default 30 min).
        window_start: Optional window boundary. If provided, detects a gap
            before the first entry (boundary-start gap).
        window_end: Optional window boundary. If provided, detects a gap
            after the last entry (boundary-end gap).

    Returns:
        List of gap dicts, each with keys:
            - after_entry_id (str | None): Page ID of entry before gap.
            - before_entry_id (str | None): Page ID of entry after gap.
            - start (datetime): Gap start time.
            - end (datetime): Gap end time.
            - hours (float): Gap duration in hours.
            - boundary (str | None): "start" for window-start gap,
              "end" for window-end gap, None for between-entry gaps.
    """
    threshold_hrs = threshold_minutes / 60.0
    gaps: List[Dict[str, Any]] = []

    # Filter entries with both start and end
    valid_entries = [
        e for e in entries if e.get("start") and e.get("end")
    ]
    if not valid_entries:
        return gaps

    # Boundary-start gap (before first entry)
    if window_start is not None:
        first_start = valid_entries[0].get("start")
        if first_start and first_start > window_start:
            gap_hrs = (first_start - window_start).total_seconds() / 3600
            if gap_hrs >= threshold_hrs:
                gaps.append({
                    "after_entry_id": None,
                    "before_entry_id": valid_entries[0].get("page_id"),
                    "start": window_start,
                    "end": first_start,
                    "hours": round(gap_hrs, 2),
                    "boundary": "start",
                })

    # Between-entry gaps
    for i in range(len(valid_entries) - 1):
        curr_end = valid_entries[i].get("end")
        next_start = valid_entries[i + 1].get("start")
        if curr_end and next_start:
            gap_hrs = (next_start - curr_end).total_seconds() / 3600
            if gap_hrs >= threshold_hrs:
                gaps.append({
                    "after_entry_id": valid_entries[i].get("page_id"),
                    "before_entry_id": valid_entries[i + 1].get("page_id"),
                    "start": curr_end,
                    "end": next_start,
                    "hours": round(gap_hrs, 2),
                    "boundary": None,
                })

    # Boundary-end gap (after last entry)
    if window_end is not None:
        last_end = valid_entries[-1].get("end")
        if last_end and last_end < window_end:
            gap_hrs = (window_end - last_end).total_seconds() / 3600
            if gap_hrs >= threshold_hrs:
                gaps.append({
                    "after_entry_id": valid_entries[-1].get("page_id"),
                    "before_entry_id": None,
                    "start": last_end,
                    "end": window_end,
                    "hours": round(gap_hrs, 2),
                    "boundary": "end",
                })

    return gaps


# ── Update / Edit ─────────────────────────────────────────────────────────────


async def update_entry_type(page_id: str, new_type: str, notes: Optional[str] = None) -> Dict[str, Any]:
    """Updates the activity type of an entry by modifying the Name property.

    The Name property follows the pattern "Type - Description". When changing
    the type, the description is preserved unless explicitly overridden.

    Args:
        page_id: The Notion page ID of the entry.
        new_type: The new activity type name.
        notes: Optional new description. If None, preserves existing description.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_title (str | None): The previous title (for undo support).
            - new_title (str | None): The updated title.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_title": None,
            "new_title": None,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        # Fetch current entry to get the existing title
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            # If we can't fetch, just update with the new type
            old_title = ""
            old_props = {}
        else:
            entry = detail["entry"]
            old_title = entry.get("title", "")
            parts = old_title.split(" - ", 1)
            if notes is None:
                notes = parts[1] if len(parts) > 1 else ""
            old_props = {"Name": NB.title(old_title)}

        new_title = f"{new_type} - {notes}" if notes else new_type
        await notion_manager.update_page(page_id, {"Name": NB.title(new_title)})

        return {
            "success": True,
            "old_title": old_title,
            "new_title": new_title,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to update type for %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "old_title": None,
            "new_title": None,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_time(
    page_id: str,
    start: datetime,
    end: datetime,
) -> Dict[str, Any]:
    """Updates the start and end times of an activity entry.

    Always sets both start and end (Notion requires the full Date object).

    Args:
        page_id: The Notion page ID of the entry.
        start: New start datetime (timezone-aware, IST).
        end: New end datetime (timezone-aware, IST).

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_properties (dict | None): Previous Date properties (for undo).
            - new_duration_hrs (float | None): The updated duration.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_properties": None,
            "new_duration_hrs": None,
            "page_id": "",
            "error": "No page_id provided",
        }

    if start >= end:
        return {
            "success": False,
            "old_properties": None,
            "new_duration_hrs": None,
            "page_id": page_id,
            "error": "Start time must be before end time",
        }

    try:
        # Fetch current entry for undo support
        detail = await get_entry_detail(page_id)
        old_properties = None
        if detail["found"] and detail["entry"]:
            entry = detail["entry"]
            old_start = entry.get("start")
            old_end = entry.get("end")
            if old_start and old_end:
                old_properties = {
                    "Date": NB.date(
                        old_start.isoformat(), end_iso=old_end.isoformat()
                    )
                }

        await notion_manager.update_page(
            page_id,
            {"Date": NB.date(start.isoformat(), end_iso=end.isoformat())},
        )

        new_duration_hrs = (end - start).total_seconds() / 3600

        return {
            "success": True,
            "old_properties": old_properties,
            "new_duration_hrs": round(new_duration_hrs, 2),
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to update time for %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "old_properties": None,
            "new_duration_hrs": None,
            "page_id": page_id,
            "error": str(e),
        }


def calculate_offset(start: str, offset_minutes: int) -> str:
    """Calculates a new ISO datetime string by applying a time offset.

    Useful for time shortcut buttons (add/subtract 15/30/45/60/90/120 min).

    Args:
        start: ISO datetime string to offset from.
        offset_minutes: Minutes to add (positive) or subtract (negative).

    Returns:
        ISO format datetime string at the nearest 15-minute interval.
    """
    dt = datetime.fromisoformat(start)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    result = round_to_15(dt + timedelta(minutes=offset_minutes))
    return result.isoformat()


# ── Delete / Archive ──────────────────────────────────────────────────────────


async def delete_entry(page_id: str) -> Dict[str, Any]:
    """Archives (soft-deletes) an activity entry in Notion.

    The entry is archived, not permanently deleted, allowing undo.

    Args:
        page_id: The Notion page ID of the entry to delete.

    Returns:
        A dict with keys:
            - success (bool): Whether the deletion succeeded.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        await notion_manager.delete_page(page_id)
        logger.info("Deleted activity entry: page_id=%s", page_id)
        return {
            "success": True,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to delete entry %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "page_id": page_id,
            "error": str(e),
        }
