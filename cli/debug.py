"""
LifeOS CLI — Debugging and diagnostic commands.

One-shot diagnostics that inspect service health, cache status, Notion
consistency, conversation state machines, and feature parity.

Usage:
    lifeos debug notion-consistency --page_id <id>
    lifeos debug timeline-verify <page_id>
    lifeos debug cache-status
    lifeos debug service-health
    lifeos debug audit-telegram-parity
    lifeos debug state-machine
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import typer

from services import activity, financial, diet, journal, dashboard
from cli.format import output as fmt_output

logger = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=5, minutes=30))

app = typer.Typer(help="Debugging and diagnostics")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _call_async(coro):
    """Bridge an async service call into a synchronous CLI command."""
    return asyncio.run(coro)


def _emit(data: dict, fmt: str) -> None:
    """Format and print output."""
    print(fmt_output(data, fmt))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Notion Consistency
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("notion-consistency")
def notion_consistency(
    page_id: str = typer.Option(None, help="Page ID to search for"),
    minutes_ago: int = typer.Option(5, help="Look-back window in minutes"),
    format: str = typer.Option("toon", help="Output format: toon, rich, text"),
):
    """Check Notion eventual consistency status.

    Queries recent activity entries and checks if the specified page_id
    appears in the result set.  Reports timing, staleness, and whether
    the page has been indexed yet.
    """
    window_start = (datetime.now(TZ) - timedelta(minutes=minutes_ago)).date().isoformat()
    window_end = (datetime.now(TZ) + timedelta(minutes=1)).date().isoformat()

    t0 = time.monotonic()
    try:
        entries = _call_async(
            activity.get_activity_entries(
                date_from=window_start,
                date_to=window_end,
                limit=50,
                sort_ascending=False,
            )
        )
        query_time = round(time.monotonic() - t0, 3)

        found = False
        entry = None
        if page_id:
            for e in entries:
                if e.get("page_id") == page_id:
                    found = True
                    entry = e
                    break

        _emit(
            {
                "page_id": page_id or "(not specified)",
                "found": found,
                "entry": entry,
                "query_time_seconds": query_time,
                "result_count": len(entries),
                "window_minutes": minutes_ago,
                "window_start": window_start,
                "window_end": window_end,
                "consistency_status": "indexed" if found else "not_found" if page_id else "no_check",
            },
            format,
        )
    except Exception as exc:
        logger.exception("notion-consistency check failed")
        _emit(
            {
                "error": str(exc),
                "query_time_seconds": round(time.monotonic() - t0, 3),
            },
            format,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Timeline Verify
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("timeline-verify")
def timeline_verify(
    page_id: str = typer.Argument(..., help="Notion page ID to look up"),
    format: str = typer.Option("toon", help="Output format: toon, rich, text"),
):
    """Verify an entry appears in activity timeline queries.

    Searches a 30-day window for the specified entry and reports its
    position, surrounding entries, and time since creation.
    """
    now = datetime.now(TZ)
    date_from = (now - timedelta(days=30)).isoformat()
    date_to = (now + timedelta(days=1)).isoformat()

    t0 = time.monotonic()
    try:
        entries = _call_async(
            activity.get_activity_entries(
                date_from=date_from,
                date_to=date_to,
                limit=100,
                sort_ascending=True,
            )
        )
        query_time = round(time.monotonic() - t0, 3)

        found_idx = None
        entry = None
        for i, e in enumerate(entries):
            if e.get("page_id") == page_id:
                found_idx = i
                entry = e
                break

        surrounding = []
        if found_idx is not None:
            start = max(0, found_idx - 5)
            end = min(len(entries), found_idx + 6)
            surrounding = [
                {
                    "position": j,
                    "page_id": entries[j].get("page_id"),
                    "title": entries[j].get("title"),
                    "start": str(entries[j].get("start", "")),
                }
                for j in range(start, end)
            ]

        age_hours = None
        if entry and entry.get("start"):
            age_hours = round((now - entry["start"]).total_seconds() / 3600, 2)

        _emit(
            {
                "page_id": page_id,
                "found": found_idx is not None,
                "position": found_idx,
                "total_entries": len(entries),
                "surrounding_entries": surrounding,
                "entry": entry,
                "age_hours": age_hours,
                "query_time_seconds": query_time,
                "window_days": 30,
                "date_from": date_from,
                "date_to": date_to,
            },
            format,
        )
    except Exception as exc:
        logger.exception("timeline-verify failed")
        _emit({"error": str(exc), "page_id": page_id}, format)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Cache Status
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("cache-status")
def cache_status(format: str = typer.Option("toon", help="Output format: toon, rich, text")):
    """Show cache hit rate and staleness information.

    If the diskcache-based ``AsyncDiskCache`` is configured, try to
    inspect the volume and recent stats.  Otherwise report that the
    cache is disabled or not available.
    """
    try:
        from cache import bot_cache
        from diskcache import Cache
        from config import settings

        dircache: Cache = bot_cache._cache  # type: ignore[attr-defined]
        raw_hits, raw_misses = dircache.stats()
        hits: int = int(raw_hits) if raw_hits is not None else 0  # type: ignore[arg-type]
        misses: int = int(raw_misses) if raw_misses is not None else 0  # type: ignore[arg-type]
        total = hits + misses
        hit_rate = round(hits / total * 100, 1) if total > 0 else 0.0

        _emit(
            {
                "enabled": True,
                "directory": settings.CACHE_DIR,
                "default_ttl_seconds": settings.CACHE_DEFAULT_TTL,
                "hits": hits,
                "misses": misses,
                "hit_rate_percent": hit_rate,
                "total_requests": total,
                "volume": len(list(dircache.iterkeys())),
            },
            format,
        )
    except ImportError:
        _emit(
            {
                "enabled": False,
                "reason": "diskcache is not installed",
                "note": "Install diskcache to enable persistent caching",
            },
            format,
        )
    except AttributeError:
        _emit(
            {
                "enabled": False,
                "reason": "bot_cache instance not initialised or missing _cache attribute",
            },
            format,
        )
    except Exception as exc:
        logger.exception("cache-status failed")
        _emit({"enabled": False, "error": str(exc)}, format)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Service Health
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("service-health")
def service_health(format: str = typer.Option("toon", help="Output format: toon, rich, text")):
    """Check all service connections.

    Each registered service is tested with a lightweight query.
    Reports name, status (ok / error), response time in seconds,
    and the error message when a check fails.
    """

    async def _run_all_checks():
        """Run all health checks inside a single event loop to avoid
        httpx/Notion client caching a closed event loop."""
        checks = [
            ("Activity", activity.get_activity_stats(hours=48)),
            ("Financial", financial.get_financial_entries(limit=1)),
            ("Diet", diet.get_diet_entries(limit=1)),
            ("Journal", journal.get_subjective_entries(limit=1)),
            ("Dashboard", dashboard.get_dashboard_data()),
        ]

        results = []
        for name, coro in checks:
            t0 = time.monotonic()
            try:
                result = await coro
                elapsed = round(time.monotonic() - t0, 3)
                results.append({"service": name, "status": "ok", "response_time": elapsed, "error": None, "data": result})
            except Exception as exc:
                elapsed = round(time.monotonic() - t0, 3)
                results.append({"service": name, "status": "error", "response_time": elapsed, "error": str(exc), "data": None})
        return results

    results = _call_async(_run_all_checks())
    all_ok = all(r["status"] == "ok" for r in results)
    _emit(
        {
            "overall": "healthy" if all_ok else "degraded",
            "checks": results,
            "ok_count": sum(1 for r in results if r["status"] == "ok"),
            "error_count": sum(1 for r in results if r["status"] == "error"),
        },
        format,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Audit Telegram Parity
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("audit-telegram-parity")
def audit_parity(format: str = typer.Option("toon", help="Output format: toon, rich, text")):
    """Cross-reference Telegram features against CLI commands.

    Produces a table mapping known Telegram bot screens and features
    to their CLI equivalents, flagging gaps where no CLI command
    exists yet.
    """
    telegram_to_cli = [
        # (Telegram Feature, CLI Equivalent, Status)
        ("Main Dashboard", "direct activity --action stats + service-health", "exists"),
        ("Activity Log", "direct activity --action view", "exists"),
        ("Activity Log Entry", "direct activity --action log", "exists"),
        ("Activity Edit Type", "direct activity --action edit-type (not implemented)", "missing"),
        ("Activity Edit Time", "direct activity --action edit-time (not implemented)", "missing"),
        ("Activity Delete", "direct activity --action delete", "exists"),
        ("Activity Gaps", "direct activity --action gaps", "exists"),
        ("Activity Stats", "direct activity --action stats", "exists"),
        ("Financial Log", "direct financial --action log", "exists"),
        ("Financial View", "direct financial --action view", "exists"),
        ("Financial Summary", "direct financial --action summary", "exists"),
        ("Financial Categories", "direct financial --action categories", "exists"),
        ("Diet Log", "direct diet --action log", "exists"),
        ("Diet View", "direct diet --action view", "exists"),
        ("Diet Meal Types", "direct diet --action meals", "exists"),
        ("Journal Subjective", "direct journal --journal-type subjective", "exists"),
        ("Journal Relational", "direct journal --journal-type relational", "exists"),
        ("Journal Systemic", "direct journal --journal-type systemic", "exists"),
        ("Notion Consistency Check", "debug notion-consistency", "exists"),
        ("Timeline Verification", "debug timeline-verify", "exists"),
        ("Cache Status", "debug cache-status", "exists"),
        ("Service Health", "debug service-health", "exists"),
        ("Conversation Simulator", "simulate send", "exists"),
    ]

    present = sum(1 for _, _, s in telegram_to_cli if s == "exists")
    missing_items = [(f, c) for f, c, s in telegram_to_cli if s == "missing"]

    _emit(
        {
            "total_features": len(telegram_to_cli),
            "cli_present": present,
            "cli_missing": len(missing_items),
            "coverage_pct": round(present / len(telegram_to_cli) * 100, 1),
            "mapping": [{"telegram": t, "cli": c, "status": s} for t, c, s in telegram_to_cli],
            "gaps": [{"telegram": t, "suggested_cli": c} for t, c in missing_items],
        },
        format,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. State Machine
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("state-machine")
def state_machine(format: str = typer.Option("toon", help="Output format: toon, rich, text")):
    """Dump all valid conversation states and transitions.

    Shows the complete state machine graph as a reference table.
    States map to Telegram conversation handler entry points.
    Transitions are triggered by callback data or text patterns.
    """
    # Known states from bot/main.py conversation handlers.
    # These are hardcoded as a reference since the CLI cannot import
    # from bot/ handlers (architectural boundary).
    state_definitions = [
        {"state": "ACTIVITY_LOG", "handler": "activity", "description": "Awaiting activity log input (type/start/end)"},
        {"state": "ACTIVITY_EDIT_TYPE", "handler": "activity", "description": "Awaiting new activity type for edit"},
        {"state": "ACTIVITY_EDIT_TIME", "handler": "activity", "description": "Awaiting new start/end time"},
        {"state": "FINANCIAL_LOG", "handler": "financial", "description": "Awaiting financial entry details"},
        {"state": "DIET_LOG", "handler": "diet", "description": "Awaiting diet entry details"},
        {"state": "JOURNAL_SUBJECTIVE", "handler": "journal", "description": "Awaiting subjective journal entry"},
        {"state": "JOURNAL_RELATIONAL", "handler": "journal", "description": "Awaiting relational journal entry"},
        {"state": "JOURNAL_SYSTEMIC", "handler": "journal", "description": "Awaiting systemic journal entry"},
        {"state": "AWAITING_START", "handler": "base", "description": "Awaiting activity start time"},
        {"state": "AWAITING_END", "handler": "base", "description": "Awaiting activity end time"},
        {"state": "AWAITING_DURATION", "handler": "base", "description": "Awaiting activity duration"},
        {"state": "AWAITING_ACTIVITY_TYPE", "handler": "base", "description": "Awaiting activity type selection"},
        {"state": "AWAITING_FINANCIAL_TYPE", "handler": "financial", "description": "Awaiting expense/income selection"},
        {"state": "AWAITING_FINANCIAL_AMOUNT", "handler": "financial", "description": "Awaiting transaction amount"},
        {"state": "AWAITING_FINANCIAL_CATEGORY", "handler": "financial", "description": "Awaiting category selection"},
        {"state": "AWAITING_DIET_MEAL_TYPE", "handler": "diet", "description": "Awaiting meal type selection"},
        {"state": "AWAITING_DIET_DESCRIPTION", "handler": "diet", "description": "Awaiting meal description"},
        {"state": "AWAITING_DIET_CALORIES", "handler": "diet", "description": "Awaiting calorie count (optional)"},
    ]

    # High-level transition groups.
    transitions = [
        {"from": "START", "trigger": "/log", "to": "ACTIVITY_LOG"},
        {"from": "START", "trigger": "/financial", "to": "FINANCIAL_LOG"},
        {"from": "START", "trigger": "/diet", "to": "DIET_LOG"},
        {"from": "START", "trigger": "/journal", "to": "JOURNAL_SUBJECTIVE"},
        {"from": "START", "trigger": "main_menu callbacks", "to": "various states"},
        {"from": "ACTIVITY_LOG", "trigger": "type selected", "to": "AWAITING_START"},
        {"from": "AWAITING_START", "trigger": "time entered", "to": "AWAITING_END"},
        {"from": "AWAITING_END", "trigger": "time entered", "to": "AWAITING_DURATION or complete"},
        {"from": "ACTIVITY_EDIT_TYPE", "trigger": "new type selected", "to": "complete"},
        {"from": "ACTIVITY_EDIT_TIME", "trigger": "time entered", "to": "complete"},
        {"from": "FINANCIAL_LOG", "trigger": "type selected", "to": "AWAITING_FINANCIAL_AMOUNT"},
        {"from": "AWAITING_FINANCIAL_AMOUNT", "trigger": "amount entered", "to": "AWAITING_FINANCIAL_CATEGORY"},
        {"from": "AWAITING_FINANCIAL_CATEGORY", "trigger": "category selected", "to": "complete"},
        {"from": "DIET_LOG", "trigger": "meal type selected", "to": "AWAITING_DIET_DESCRIPTION"},
        {"from": "AWAITING_DIET_DESCRIPTION", "trigger": "description entered", "to": "AWAITING_DIET_CALORIES"},
        {"from": "AWAITING_DIET_CALORIES", "trigger": "calories or skip", "to": "complete"},
        {"from": "JOURNAL_SUBJECTIVE", "trigger": "fields filled", "to": "complete"},
        {"from": "JOURNAL_RELATIONAL", "trigger": "fields filled", "to": "complete"},
        {"from": "JOURNAL_SYSTEMIC", "trigger": "fields filled", "to": "complete"},
    ]

    _emit(
        {
            "state_count": len(state_definitions),
            "transition_count": len(transitions),
            "states": state_definitions,
            "transitions": transitions,
        },
        format,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI entry point (if run directly)
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app()
