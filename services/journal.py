# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/services/journal.py
#
# Journal Service Layer — pure business logic for journal operations.
#
# Provides functions to save and query journal entries across three journals:
#   - Subjective: energy, focus, happiness, gratitude
#   - Relational: person, connection quality, insights
#   - Systemic:  bottlenecks, actionable items, done
#
# No Telegram dependencies.  Consumes NotionClientManager from the notion
# package and returns plain dicts.  Both the Telegram bot and CLI simulator
# use these functions.

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import settings
from notion.client import notion_manager
from notion.models import NotionPayloadBuilder as NB

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Property builders (internal helpers)
# ---------------------------------------------------------------------------

def _build_subjective_properties(
    energy: Optional[int],
    focus: Optional[int],
    happiness: Optional[int],
    gratitude: str,
    date: str,
) -> Dict[str, Any]:
    """Build the Notion properties dict for a subjective journal entry.

    Only includes numeric fields when they are not None so that the API
    does not receive null values for optional properties.
    """
    parts: list[str] = []
    if energy is not None:
        parts.append(f"E:{energy}")
    if focus is not None:
        parts.append(f"F:{focus}")
    if happiness is not None:
        parts.append(f"H:{happiness}")
    title_str = " | ".join(parts) if parts else "Journal Entry"

    properties: Dict[str, Any] = {
        "Name": NB.title(f"{date} \u2014 {title_str}"),
        "Date": NB.date(date),
        "Gratitude": NB.rich_text(gratitude),
    }
    if energy is not None:
        properties["Energy"] = NB.number(energy)
    if focus is not None:
        properties["Focus"] = NB.number(focus)
    if happiness is not None:
        properties["Happiness"] = NB.number(happiness)
    return properties


def _build_relational_properties(
    person: str,
    connection_quality: Optional[int],
    insights: str,
    date: str,
) -> Dict[str, Any]:
    """Build the Notion properties dict for a relational journal entry."""
    properties: Dict[str, Any] = {
        "Name": NB.title(f"{person} \u2014 {date}"),
        "Date": NB.date(date),
        "Insights": NB.rich_text(insights),
    }
    if connection_quality is not None:
        properties["Connection Quality"] = NB.number(connection_quality)
    return properties


def _build_systemic_properties(
    bottlenecks: str,
    actionable_items: str,
    date: str,
) -> Dict[str, Any]:
    """Build the Notion properties dict for a systemic journal entry."""
    return {
        "Name": NB.title(f"Systemic Review \u2014 {date}"),
        "Date": NB.date(date),
        "Bottlenecks": NB.rich_text(bottlenecks),
        "Actionable Items": NB.rich_text(actionable_items),
        "Done": NB.checkbox(False),
    }


# ---------------------------------------------------------------------------
# Save functions
# ---------------------------------------------------------------------------

async def save_subjective_entry(
    energy: Optional[int] = None,
    focus: Optional[int] = None,
    happiness: Optional[int] = None,
    gratitude: str = "",
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a subjective journal entry in Notion.

    Parameters
    ----------
    energy : int or None
        Energy rating (1–10).  Omitted from Notion when None.
    focus : int or None
        Focus rating (1–10).  Omitted from Notion when None.
    happiness : int or None
        Happiness rating (1–10).  Omitted from Notion when None.
    gratitude : str
        Free-text gratitude entry.  Defaults to empty.
    date : str or None
        ISO-8601 date (``YYYY-MM-DD``).  Defaults to **today UTC**.

    Returns
    -------
    dict
        ``{"success": True, "message": str, "data": dict}`` on success or
        ``{"success": False, "message": str}`` on failure.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    properties = _build_subjective_properties(energy, focus, happiness, gratitude, date)

    try:
        result = await notion_manager.create_page(
            settings.DATABASE_ID_SUBJECTIVE_JOURNAL, properties
        )
        parts = " | ".join(
            p
            for p in [
                f"E:{energy}" if energy is not None else None,
                f"F:{focus}" if focus is not None else None,
                f"H:{happiness}" if happiness is not None else None,
            ]
            if p is not None
        )
        title_str = parts or "Journal Entry"
        return {"success": True, "message": f"Subjective journal logged: {title_str}", "data": result}
    except Exception as exc:
        logger.exception("Failed to save subjective journal entry")
        return {"success": False, "message": str(exc)}


async def save_relational_entry(
    person: str,
    connection_quality: Optional[int] = None,
    insights: str = "",
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a relational journal entry in Notion.

    Parameters
    ----------
    person : str
        Name of the person you interacted with.
    connection_quality : int or None
        Connection quality rating (1–10).  Omitted when None.
    insights : str
        Free-text insights from the interaction.  Defaults to empty.
    date : str or None
        ISO-8601 date (``YYYY-MM-DD``).  Defaults to **today UTC**.

    Returns
    -------
    dict
        ``{"success": True, "message": str, "data": dict}`` on success or
        ``{"success": False, "message": str}`` on failure.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    properties = _build_relational_properties(person, connection_quality, insights, date)

    try:
        result = await notion_manager.create_page(
            settings.DATABASE_ID_RELATIONAL_JOURNAL, properties
        )
        return {"success": True, "message": f"Relational journal logged: {person}", "data": result}
    except Exception as exc:
        logger.exception("Failed to save relational journal entry")
        return {"success": False, "message": str(exc)}


async def save_systemic_entry(
    bottlenecks: str = "",
    actionable_items: str = "",
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a systemic journal entry in Notion.

    Parameters
    ----------
    bottlenecks : str
        Description of current bottlenecks or friction points.
    actionable_items : str
        Actionable changes or solutions you can try.
    date : str or None
        ISO-8601 date (``YYYY-MM-DD``).  Defaults to **today UTC**.

    Returns
    -------
    dict
        ``{"success": True, "message": str, "data": dict}`` on success or
        ``{"success": False, "message": str}`` on failure.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    properties = _build_systemic_properties(bottlenecks, actionable_items, date)

    try:
        result = await notion_manager.create_page(
            settings.DATABASE_ID_SYSTEMIC_JOURNAL, properties
        )
        return {"success": True, "message": "Systemic journal logged.", "data": result}
    except Exception as exc:
        logger.exception("Failed to save systemic journal entry")
        return {"success": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Query helpers (internal)
# ---------------------------------------------------------------------------

def _parse_journal_entry(
    page: Dict[str, Any],
    property_map: Dict[str, str],
) -> Dict[str, Any]:
    """Parse a raw Notion API page response into a clean journal entry dict.

    Parameters
    ----------
    page : dict
        A single ``results[]`` item from a Notion database-query response.
    property_map : dict
        Maps output key names to **Notion property names**, plus the special
        keys ``"title"`` and ``"date"`` to identify those properties.

    Returns
    -------
    dict
        Flat dictionary with keys matching ``property_map`` (minus the
        ``"title"`` / ``"date"`` routing keys) plus ``"page_id"``.
        Returns an empty dict when parsing fails.
    """
    try:
        props = page.get("properties", {})

        # -- Title (always present) --
        title_key = property_map.get("title", "Name")
        title_parts = props.get(title_key, {}).get("title", [])
        title = "".join(p.get("plain_text", "") for p in title_parts)

        # -- Date (always present) --
        date_key = property_map.get("date", "Date")
        date_prop = props.get(date_key, {}).get("date", {}) or {}
        date_str = date_prop.get("start", "")

        entry: Dict[str, Any] = {
            "page_id": page.get("id", ""),
            "title": title,
            "date": date_str,
        }

        # -- Everything else, dispatched by Notion type --
        for output_key, notion_prop_name in property_map.items():
            if output_key in ("title", "date"):
                continue
            prop = props.get(notion_prop_name, {})
            prop_type = prop.get("type", "")

            if prop_type == "rich_text":
                text_parts = prop.get("rich_text", [])
                entry[output_key] = "".join(
                    p.get("plain_text", "") for p in text_parts
                )
            elif prop_type == "number":
                entry[output_key] = prop.get("number")
            elif prop_type == "checkbox":
                entry[output_key] = prop.get("checkbox", False)
            else:
                entry[output_key] = None

        return entry
    except Exception as exc:
        logger.error("Failed to parse journal entry: %s", exc)
        return {}


async def _query_journal_entries(
    database_id: str,
    property_map: Dict[str, str],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Query journal entries from a Notion database.

    Parameters
    ----------
    database_id : str
        Notion database ID to query.
    property_map : dict
        Passed through to :func:`_parse_journal_entry`.
    date_from : str or None
        ISO-8601 date — only entries **on or after** this date are returned.
    date_to : str or None
        ISO-8601 date — only entries **before** this date are returned.
    limit : int
        Max number of entries (capped at 100 by the Notion API per page).

    Returns
    -------
    list[dict]
        Parsed entries sorted by ``Date`` descending (newest first).
    """
    body: Dict[str, Any] = {
        "page_size": min(limit, 100),
        "sorts": [{"property": "Date", "direction": "descending"}],
    }

    if date_from or date_to:
        date_filter: Dict[str, str] = {}
        if date_from:
            date_filter["on_or_after"] = date_from
        if date_to:
            date_filter["before"] = date_to
        body["filter"] = {"and": [{"property": "Date", "date": date_filter}]}

    try:
        response = await notion_manager.client.request(
            path=f"databases/{database_id}/query",
            method="POST",
            body=body,
        )
    except Exception as exc:
        logger.exception("Failed to query journal entries for DB %s", database_id)
        return []

    entries: List[Dict[str, Any]] = []
    for page in response.get("results", []):
        parsed = _parse_journal_entry(page, property_map)
        if parsed:
            entries.append(parsed)

    return entries[:limit]


# ---------------------------------------------------------------------------
# Query functions (public API)
# ---------------------------------------------------------------------------

async def get_subjective_entries(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return subjective journal entries from Notion.

    Parameters
    ----------
    date_from, date_to : str or None
        ISO-8601 date range filter.
    limit : int
        Maximum entries to return.

    Returns
    -------
    list[dict]
        Each dict contains the keys ``page_id``, ``title``, ``date``,
        ``gratitude``, ``energy``, ``focus``, ``happiness``.
    """
    property_map = {
        "title": "Name",
        "date": "Date",
        "gratitude": "Gratitude",
        "energy": "Energy",
        "focus": "Focus",
        "happiness": "Happiness",
    }
    return await _query_journal_entries(
        settings.DATABASE_ID_SUBJECTIVE_JOURNAL,
        property_map,
        date_from,
        date_to,
        limit,
    )


async def get_relational_entries(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return relational journal entries from Notion.

    Parameters
    ----------
    date_from, date_to : str or None
        ISO-8601 date range filter.
    limit : int
        Maximum entries to return.

    Returns
    -------
    list[dict]
        Each dict contains the keys ``page_id``, ``title``, ``date``,
        ``insights``, ``connection_quality``.
    """
    property_map = {
        "title": "Name",
        "date": "Date",
        "insights": "Insights",
        "connection_quality": "Connection Quality",
    }
    return await _query_journal_entries(
        settings.DATABASE_ID_RELATIONAL_JOURNAL,
        property_map,
        date_from,
        date_to,
        limit,
    )


async def get_systemic_entries(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return systemic journal entries from Notion.

    Parameters
    ----------
    date_from, date_to : str or None
        ISO-8601 date range filter.
    limit : int
        Maximum entries to return.

    Returns
    -------
    list[dict]
        Each dict contains the keys ``page_id``, ``title``, ``date``,
        ``bottlenecks``, ``actionable_items``, ``done``.
    """
    property_map = {
        "title": "Name",
        "date": "Date",
        "bottlenecks": "Bottlenecks",
        "actionable_items": "Actionable Items",
        "done": "Done",
    }
    return await _query_journal_entries(
        settings.DATABASE_ID_SYSTEMIC_JOURNAL,
        property_map,
        date_from,
        date_to,
        limit,
    )
