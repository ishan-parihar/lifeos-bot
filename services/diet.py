# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/services/diet.py

"""Diet log service — pure business logic for diet entry management.

This module provides the service layer for diet logging operations.
It is consumed by the Telegram bot handler and the CLI simulator.
No Telegram dependencies are imported here.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import settings
from notion.client import notion_manager
from notion.models import NotionPayloadBuilder as NB

logger = logging.getLogger(__name__)


async def get_meal_types() -> List[str]:
    """Fetch available meal type options from the Notion select property.

    Falls back to default meal types ["Breakfast", "Lunch", "Dinner", "Snack"]
    if the Notion database is not configured or the fetch fails.

    Returns:
        List of meal type option names.
    """
    meals = await notion_manager.get_select_property_options(
        database_id=settings.DATABASE_ID_DIET_LOG,
        property_name="Meal Type",
    )
    if not meals:
        meals = ["Breakfast", "Lunch", "Dinner", "Snack"]
    return meals


async def save_diet_entry(
    meal_type: str,
    meal_description: str,
    date: Optional[str] = None,
    notes: str = "",
    calories: Optional[int] = None,
) -> Dict[str, Any]:
    """Save a diet entry to Notion with eventual consistency handling.

    Builds the Notion page properties and creates a new page in the
    diet log database. After creation, re-queries entries ±1 day around
    the entry date to confirm the save. If Notion hasn't indexed the new
    page yet (eventual consistency delay), a synthetic entry is constructed
    in-memory.

    Args:
        meal_type: Type of meal (e.g., "Breakfast", "Lunch", "Dinner", "Snack").
        meal_description: Description of what was eaten.
        date: ISO 8601 datetime string. Defaults to current UTC datetime
            if not provided.
        notes: Optional notes about the meal.
        calories: Optional calorie count.

    Returns:
        Dict with keys:
            - success (bool): True if saved, False otherwise.
            - page_id (str): The Notion page ID of the saved entry.
            - entry (dict | None): The saved entry (real or synthetic).
            - synthetic (bool): True if entry was injected due to eventual consistency.
            - surrounding_entries (list[dict]): Entries around the saved one.
            - all_entries (list[dict]): All entries in the query window.
            - window_start (str | None): Query window start ISO date.
            - window_end (str | None): Query window end ISO date.
            - error (str | None): Error message if success is False.
            - message (str): Human-readable result message (backward compatible).
            - data (Any): The raw Notion API response or error detail (backward compatible).
    """
    if not date:
        date = datetime.now(timezone.utc).isoformat()

    properties: Dict[str, Any] = {
        "Name": NB.title(f"{meal_type}: {meal_description}"),
        "Meal Type": NB.select(meal_type),
        "Meal Description": NB.rich_text(meal_description),
        "Date": NB.date(date),
        "Notes": NB.rich_text(notes),
    }
    if calories is not None:
        properties["Calories"] = NB.number(calories)

    try:
        result = await notion_manager.create_page(
            database_id=settings.DATABASE_ID_DIET_LOG,
            properties=properties,
        )
        new_page_id = result.get("id", "")
        msg = f"Logged {meal_type}: {meal_description}"
        if calories:
            msg += f" ({calories} cal)"

        # ── Re-query entries around the entry's date ──
        try:
            entry_date = datetime.fromisoformat(date).date()
        except (ValueError, TypeError):
            entry_date = datetime.now(timezone.utc).date()

        window_start_dt = entry_date - timedelta(days=1)
        window_end_dt = entry_date + timedelta(days=2)
        window_start = window_start_dt.isoformat()
        window_end = window_end_dt.isoformat()

        query_body: Dict[str, Any] = {
            "page_size": 50,
            "sorts": [{"property": "Date", "direction": "descending"}],
            "filter": {
                "and": [
                    {"property": "Date", "date": {"on_or_after": window_start}},
                    {"property": "Date", "date": {"before": window_end}},
                ]
            },
        }

        try:
            query_response = await notion_manager.client.request(
                path=f"databases/{settings.DATABASE_ID_DIET_LOG}/query",
                method="POST",
                body=query_body,
            )
        except Exception:
            query_response = {"results": []}

        # Parse entries
        fresh_entries: List[Dict[str, Any]] = []
        for page in query_response.get("results", []):
            entry = _parse_diet_entry(page)
            if entry:
                fresh_entries.append(entry)
        # Sort ascending by date for consistent ordering
        fresh_entries.sort(key=lambda e: e.get("date", ""))

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
                "Entry (page_id=%s) not found in fresh query — "
                "Notion eventual consistency; injecting synthetic entry",
                new_page_id,
            )
            entry = {
                "page_id": new_page_id,
                "name": f"{meal_type}: {meal_description}",
                "meal_type": meal_type,
                "description": meal_description,
                "date": date,
                "notes": notes,
                "calories": calories,
            }
            fresh_entries.append(entry)
            fresh_entries.sort(key=lambda e: e.get("date", ""))
            # Re-find index after sort
            for i, e in enumerate(fresh_entries):
                if e.get("page_id") == new_page_id:
                    saved_idx = i
                    break
            synthetic = True
            logger.info(
                "Injected synthetic entry at position %d/%d",
                saved_idx,
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
            "message": msg,
            "data": result,
        }
    except Exception as e:
        logger.error(f"Failed to save diet entry: {e}")
        return {
            "success": False,
            "page_id": "",
            "entry": None,
            "synthetic": False,
            "surrounding_entries": [],
            "all_entries": [],
            "window_start": None,
            "window_end": None,
            "error": str(e),
            "message": f"Error saving to Notion: {e}",
            "data": None,
        }


async def get_diet_entries(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Query diet entries from Notion, optionally filtered by date range.

    Args:
        date_from: ISO 8601 date string for the start of the range (inclusive).
        date_to: ISO 8601 date string for the end of the range (exclusive).
        limit: Maximum number of entries to return (default: 50).

    Returns:
        List of parsed diet entry dicts, each with keys:

        - ``page_id``: Notion page ID.
        - ``name``: Entry title (e.g., "Lunch: salad").
        - ``meal_type``: Meal type string.
        - ``description``: Meal description text.
        - ``date``: ISO datetime string.
        - ``notes``: Notes text.
        - ``calories``: Calorie count (int or None).
    """
    filter_conditions: List[Dict[str, Any]] = []
    if date_from:
        filter_conditions.append(
            {"property": "Date", "date": {"on_or_after": date_from}}
        )
    if date_to:
        filter_conditions.append(
            {"property": "Date", "date": {"before": date_to}}
        )

    body: Dict[str, Any] = {
        "page_size": limit,
        "sorts": [{"property": "Date", "direction": "descending"}],
    }
    if filter_conditions:
        body["filter"] = {"and": filter_conditions}

    try:
        response = await notion_manager.client.request(
            path=f"databases/{settings.DATABASE_ID_DIET_LOG}/query",
            method="POST",
            body=body,
        )
    except Exception as e:
        logger.error(f"Failed to query diet entries: {e}")
        return []

    entries: List[Dict[str, Any]] = []
    for page in response.get("results", []):
        entry = _parse_diet_entry(page)
        if entry:
            entries.append(entry)

    return entries


async def get_entry_detail(page_id: str) -> Dict[str, Any]:
    """Retrieves a single diet entry by page_id.

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
        now = datetime.now(timezone.utc)
        month_ago = (now - timedelta(days=30)).isoformat()
        tomorrow = (now + timedelta(days=1)).isoformat()

        body: Dict[str, Any] = {
            "page_size": 50,
            "sorts": [{"property": "Date", "direction": "descending"}],
            "filter": {
                "and": [
                    {"property": "Date", "date": {"on_or_after": month_ago}},
                    {"property": "Date", "date": {"before": tomorrow}},
                ]
            },
        }

        response = await notion_manager.client.request(
            path=f"databases/{settings.DATABASE_ID_DIET_LOG}/query",
            method="POST",
            body=body,
        )

        for page in response.get("results", []):
            parsed = _parse_diet_entry(page)
            if parsed and parsed.get("page_id") == page_id:
                return {"found": True, "entry": parsed, "error": None}

        return {"found": False, "entry": None, "error": "Entry not found"}
    except Exception as e:
        logger.error(f"Failed to fetch entry {page_id}: {e}")
        return {"found": False, "entry": None, "error": str(e)}


def _parse_diet_entry(page: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a raw Notion page into a structured diet entry dict.

    Args:
        page: Raw Notion API page object.

    Returns:
        Parsed diet entry dict, or None if parsing fails.
    """
    try:
        props = page.get("properties", {})

        # Title
        title_parts = props.get("Name", {}).get("title", [])
        name = "".join(p.get("plain_text", "") for p in title_parts)

        # Meal type (select)
        meal_type_prop = props.get("Meal Type", {}).get("select")
        meal_type = meal_type_prop.get("name", "") if meal_type_prop else ""

        # Description (rich text)
        desc_parts = props.get("Meal Description", {}).get("rich_text", [])
        description = "".join(p.get("plain_text", "") for p in desc_parts)

        # Date
        date_prop = props.get("Date", {}).get("date", {})
        date_str = date_prop.get("start", "") if date_prop else ""

        # Notes (rich text)
        notes_parts = props.get("Notes", {}).get("rich_text", [])
        notes = "".join(p.get("plain_text", "") for p in notes_parts)

        # Calories (number)
        calories_prop = props.get("Calories", {}).get("number")

        return {
            "page_id": page.get("id", ""),
            "name": name,
            "meal_type": meal_type,
            "description": description,
            "date": date_str,
            "notes": notes,
            "calories": calories_prop,
        }
    except Exception as e:
        logger.error(f"Failed to parse diet entry: {e}")
        return None


# ── Delete / Archive ──────────────────────────────────────────────────────────


async def delete_entry(page_id: str) -> Dict[str, Any]:
    """Archives (soft-deletes) a diet entry in Notion.

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
        logger.info("Deleted diet entry: page_id=%s", page_id)
        return {
            "success": True,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Failed to delete entry {page_id}: {e}")
        return {
            "success": False,
            "page_id": page_id,
            "error": str(e),
        }


# ── Update / Edit ─────────────────────────────────────────────────────────────


async def update_entry_meal_type(page_id: str, new_type: str) -> Dict[str, Any]:
    """Updates the meal type of a diet entry.

    Updates the "Meal Type" select property and rebuilds the Name title
    to reflect the new type while preserving the description.

    Args:
        page_id: The Notion page ID of the entry.
        new_type: The new meal type name.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_type (str | None): The previous meal type (for undo support).
            - new_type (str | None): The updated meal type.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_type": None,
            "new_type": None,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            old_type = ""
            description = ""
        else:
            entry = detail["entry"]
            old_type = entry.get("meal_type", "")
            description = entry.get("description", "")

        new_name = f"{new_type}: {description}" if description else new_type
        await notion_manager.update_page(page_id, {
            "Name": NB.title(new_name),
            "Meal Type": NB.select(new_type),
        })

        return {
            "success": True,
            "old_type": old_type,
            "new_type": new_type,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Failed to update meal type for {page_id}: {e}")
        return {
            "success": False,
            "old_type": None,
            "new_type": None,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_description(page_id: str, new_desc: str) -> Dict[str, Any]:
    """Updates the meal description of a diet entry.

    Updates the "Meal Description" rich_text property and rebuilds the
    Name title to reflect the new description while preserving the meal type.

    Args:
        page_id: The Notion page ID of the entry.
        new_desc: The new meal description text.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_desc (str | None): The previous description (for undo support).
            - new_desc (str | None): The updated description.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_desc": None,
            "new_desc": None,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            old_desc = ""
            meal_type = ""
        else:
            entry = detail["entry"]
            old_desc = entry.get("description", "")
            meal_type = entry.get("meal_type", "")

        new_name = f"{meal_type}: {new_desc}" if meal_type else new_desc
        await notion_manager.update_page(page_id, {
            "Name": NB.title(new_name),
            "Meal Description": NB.rich_text(new_desc),
        })

        return {
            "success": True,
            "old_desc": old_desc,
            "new_desc": new_desc,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Failed to update description for {page_id}: {e}")
        return {
            "success": False,
            "old_desc": None,
            "new_desc": None,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_calories(page_id: str, new_calories: int) -> Dict[str, Any]:
    """Updates the calorie count of a diet entry.

    Args:
        page_id: The Notion page ID of the entry.
        new_calories: The new calorie count.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_calories (int | None): The previous calorie count (for undo support).
            - new_calories (int | None): The updated calorie count.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_calories": None,
            "new_calories": None,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        old_calories = None
        if detail["found"] and detail["entry"]:
            old_calories = detail["entry"].get("calories")

        await notion_manager.update_page(page_id, {
            "Calories": NB.number(new_calories),
        })

        return {
            "success": True,
            "old_calories": old_calories,
            "new_calories": new_calories,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Failed to update calories for {page_id}: {e}")
        return {
            "success": False,
            "old_calories": None,
            "new_calories": None,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_date(page_id: str, new_date: str) -> Dict[str, Any]:
    """Updates the date of a diet entry.

    Args:
        page_id: The Notion page ID of the entry.
        new_date: The new ISO 8601 datetime string.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_date (str | None): The previous date (for undo support).
            - new_date (str | None): The updated date.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_date": None,
            "new_date": None,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        old_date = None
        if detail["found"] and detail["entry"]:
            old_date = detail["entry"].get("date")

        await notion_manager.update_page(page_id, {
            "Date": NB.date(new_date),
        })

        return {
            "success": True,
            "old_date": old_date,
            "new_date": new_date,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Failed to update date for {page_id}: {e}")
        return {
            "success": False,
            "old_date": None,
            "new_date": None,
            "page_id": page_id,
            "error": str(e),
        }
