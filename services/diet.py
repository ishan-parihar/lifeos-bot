# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/services/diet.py

"""Diet log service — pure business logic for diet entry management.

This module provides the service layer for diet logging operations.
It is consumed by the Telegram bot handler and the CLI simulator.
No Telegram dependencies are imported here.
"""

import logging
from datetime import datetime, timezone
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
    """Save a diet entry to Notion.

    Builds the Notion page properties and creates a new page in the
    diet log database.

    Args:
        meal_type: Type of meal (e.g., "Breakfast", "Lunch", "Dinner", "Snack").
        meal_description: Description of what was eaten.
        date: ISO 8601 datetime string. Defaults to current UTC datetime
            if not provided.
        notes: Optional notes about the meal.
        calories: Optional calorie count.

    Returns:
        Dict with structure:
        - ``success``: True if saved, False otherwise.
        - ``message``: Human-readable result message.
        - ``data``: The raw Notion API response (if successful) or error detail.
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
        msg = f"Logged {meal_type}: {meal_description}"
        if calories:
            msg += f" ({calories} cal)"
        return {"success": True, "message": msg, "data": result}
    except Exception as e:
        logger.error(f"Failed to save diet entry: {e}")
        return {"success": False, "message": f"Error saving to Notion: {e}", "data": None}


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
