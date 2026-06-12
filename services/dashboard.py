"""
Dashboard business logic — pure functions, no Telegram dependency.

Extracted from bot/handlers/base.py:_build_main_dashboard.
"""

import logging
from datetime import datetime, timedelta, timezone, date
from notion.client import notion_manager

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=5, minutes=30))


async def get_dashboard_data() -> dict:
    """
    Compute main dashboard statistics for the last 48 hours.

    Returns:
        {
            "ok": True/False,
            "entries": [...],
            "total_hrs": float,
            "tracked_pct": float,
            "untracked_hrs": float,
            "last_entry": {...} | None,
            "untracked_since_hrs": float | None,
            "top_categories": [(cat, hrs), ...],
        }
    """
    try:
        now = datetime.now(TZ)
        today = date.today()
        h48_ago = now - timedelta(hours=48)

        two_days_ago = (now - timedelta(hours=48)).date().isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        all_entries = await notion_manager.query_activity_entries(two_days_ago, tomorrow)
        all_entries.sort(key=lambda e: e.get("start", datetime.min))

        def overlaps(entry):
            s = entry.get("start")
            e = entry.get("end")
            if not s:
                return False
            e = e or now
            return s < now and e > h48_ago

        entries = [e for e in all_entries if overlaps(e)]

        total_hrs = sum(e.get("duration_hrs", 0) for e in entries)
        tracked_pct = (total_hrs / 48 * 100) if total_hrs else 0
        untracked_hrs = max(0, 48 - total_hrs)

        # Last entry
        last_entry = None
        untracked_since_hrs = None
        if entries:
            last = entries[-1]
            last_entry = {
                "title": last.get("title", "") or last.get("activity_type", ""),
                "activity_type": last.get("activity_type", ""),
                "start": last.get("start"),
                "end": last.get("end"),
            }
            e = last.get("end")
            if e and e < now:
                gap = (now - e).total_seconds() / 3600
                if gap >= 1:
                    untracked_since_hrs = gap

        # Category breakdown (top 3)
        cat_hours = {}
        for e in entries:
            cat = e.get("activity_type", "Other") or "Other"
            cat_hours[cat] = cat_hours.get(cat, 0) + e.get("duration_hrs", 0)
        top_categories = sorted(cat_hours.items(), key=lambda x: -x[1])[:3]

        return {
            "ok": True,
            "entries": entries,
            "total_hrs": total_hrs,
            "tracked_pct": tracked_pct,
            "untracked_hrs": untracked_hrs,
            "last_entry": last_entry,
            "untracked_since_hrs": untracked_since_hrs,
            "top_categories": top_categories,
        }
    except Exception as e:
        logger.error(f"Failed to build main dashboard: {e}")
        return {
            "ok": False,
            "entries": [],
            "total_hrs": 0,
            "tracked_pct": 0,
            "untracked_hrs": 48,
            "last_entry": None,
            "untracked_since_hrs": None,
            "top_categories": [],
        }
