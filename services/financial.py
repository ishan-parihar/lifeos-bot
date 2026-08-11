# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/services/financial.py
"""
Financial service layer — pure business logic extracted from bot/handlers/financial.py.

Provides:
    save_financial_entry   — Save a financial transaction to the Notion log.
    get_financial_categories — Fetch available category options from the Notion schema.
    get_financial_entries  — Query stored entries with optional date filtering.
    get_financial_summary  — Aggregate totals by type and category over a date range.

No Telegram dependencies. All public functions are async and return plain dicts/lists.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import settings
from notion.client import notion_manager
from notion.models import NotionPayloadBuilder as NB

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Save
# ──────────────────────────────────────────────

async def save_financial_entry(
    type_: str,
    amount: float,
    category: str,
    date: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """
    Save a financial entry to the Notion financial log database.

    Args:
        type_: Transaction type — ``"Expense"`` or ``"Income"``.
        amount: Positive transaction amount.  Stored as a negative number for
            expenses so callers can rely on ``signed_amount`` in queries.
        category: Category name (must match a Notion select option).
        date: ISO 8601 date string.  Defaults to the current UTC timestamp.
        notes: Optional free-text note.

    Returns:
        A dict with the keys:

        - **success** (*bool*) — Whether the page was created.
        - **page_id** (*str*) — The Notion page ID of the saved entry.
        - **entry** (*dict | None*) — The saved entry (real or synthetic).
        - **synthetic** (*bool*) — True if entry was injected due to eventual consistency.
        - **surrounding_entries** (*list*) — Entries around the saved one.
        - **all_entries** (*list*) — All entries in the query window.
        - **window_start** (*str | None*) — Query window start ISO date.
        - **window_end** (*str | None*) — Query window end ISO date.
        - **data** (*dict | None*) — Saved entry metadata (backward compatible).
        - **error** (*str | None*) — Error message on failure.
    """
    if date is None:
        date = datetime.now(timezone.utc).isoformat()

    sign = -1 if type_ == "Expense" else 1
    properties = {
        "Name": NB.title(f"{type_}: {category} — {amount}"),
        "Type": NB.select(type_),
        "Amount": NB.number(sign * amount),
        "Category": NB.select(category),
        "Date": NB.date(date),
        "Notes": NB.rich_text(notes),
    }

    try:
        result = await notion_manager.create_page(
            database_id=settings.DATABASE_ID_FINANCIAL_LOG,
            properties=properties,
        )
        new_page_id = result.get("id", "")
        logger.info("Financial entry saved: page_id=%s", new_page_id)

        # ── Re-query entries around the entry's date ──
        # Parse the date to determine the query window
        if "T" in date:
            entry_dt = datetime.fromisoformat(date)
            entry_date = entry_dt.date()
        else:
            entry_date = datetime.strptime(date, "%Y-%m-%d").date()

        window_start_date = (entry_date - timedelta(days=1)).isoformat()
        window_end_date = (entry_date + timedelta(days=1)).isoformat()

        fresh_entries = await get_financial_entries(
            date_from=window_start_date,
            date_to=window_end_date,
            limit=100,
        )

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
                "Entry (page_id=%s, date=%s) not found in fresh query — "
                "Notion eventual consistency; injecting synthetic entry",
                new_page_id,
                date,
            )
            entry = {
                "page_id": new_page_id,
                "name": f"{type_}: {category} — {amount}",
                "type": type_,
                "amount": amount,
                "signed_amount": sign * amount,
                "category": category,
                "date": entry_date.isoformat(),
                "notes": notes,
            }
            # Insert at correct position (entries are sorted by date descending)
            insert_idx = len(fresh_entries)
            for i, e in enumerate(fresh_entries):
                e_date = e.get("date", "")
                if e_date >= entry_date.isoformat():
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
            "window_start": window_start_date,
            "window_end": window_end_date,
            "data": {"type": type_, "category": category, "amount": amount, "date": date},
            "error": None,
        }

    except Exception as e:
        logger.error("Failed to save financial entry: %s", e, exc_info=True)
        return {
            "success": False,
            "page_id": "",
            "entry": None,
            "synthetic": False,
            "surrounding_entries": [],
            "all_entries": [],
            "window_start": None,
            "window_end": None,
            "data": None,
            "error": str(e),
        }


# ──────────────────────────────────────────────
# Categories
# ──────────────────────────────────────────────

async def get_financial_categories() -> list[str]:
    """
    Fetch available category options from the Notion database schema
    (the ``Category`` select property).

    The result is cached by the Notion client for 24 hours.

    Falls back to a hardcoded default list when the Notion API is
    unavailable or the database ID is a placeholder.

    Returns:
        A list of category name strings.
    """
    default_categories = [
        "Food", "Transport", "Utilities", "Housing",
        "Entertainment", "Shopping", "Salary", "Other",
    ]
    try:
        categories = await notion_manager.get_select_property_options(
            database_id=settings.DATABASE_ID_FINANCIAL_LOG,
            property_name="Category",
        )
        return categories if categories else default_categories
    except Exception as e:
        logger.error("Failed to fetch financial categories: %s", e)
        return default_categories


# ──────────────────────────────────────────────
# Query entries
# ──────────────────────────────────────────────

async def get_financial_entries(
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Query financial log entries from Notion, sorted by Date descending.

    .. code-block:: python

        entries = await get_financial_entries(
            date_from="2025-01-01", date_to="2025-12-31", limit=100,
        )

    Args:
        date_from: Optional ISO date string — include entries on or after
            this date.
        date_to: Optional ISO date string — include entries on or before
            this date.
        limit: Maximum number of results (default 50).

    Returns:
        A list of parsed entry dicts, each with the keys:

        - **page_id** (*str*) — Notion page ID.
        - **name** (*str*) — ``Name`` title text.
        - **type** (*str*) — ``"Expense"`` or ``"Income"``.
        - **amount** (*float*) — Absolute value of the transaction.
        - **signed_amount** (*float*) — Signed value (negative for expenses).
        - **category** (*str*) — Category name.
        - **date** (*str*) — ISO date string.
        - **notes** (*str*) — Free-text notes.

        An empty list is returned on any error.
    """
    body: dict[str, Any] = {
        "sorts": [{"property": "Date", "direction": "descending"}],
        "page_size": limit,
    }

    filters = []
    if date_from:
        filters.append({"property": "Date", "date": {"on_or_after": date_from}})
    if date_to:
        filters.append({"property": "Date", "date": {"on_or_before": date_to}})

    if len(filters) == 1:
        body["filter"] = filters[0]
    elif len(filters) > 1:
        body["filter"] = {"and": filters}

    try:
        response = await notion_manager.client.request(
            path=f"databases/{settings.DATABASE_ID_FINANCIAL_LOG}/query",
            method="POST",
            body=body,
        )
        entries = []
        for page in response.get("results", []):
            parsed = _parse_financial_entry(page)
            if parsed:
                entries.append(parsed)
        return entries
    except Exception as e:
        logger.error("Failed to query financial entries: %s", e)
        return []


# ──────────────────────────────────────────────
# Summary / aggregation
# ──────────────────────────────────────────────

async def get_financial_summary(
    date_from: str,
    date_to: str,
) -> dict[str, Any]:
    """
    Compute a summary of financial activity over a date range.

    Args:
        date_from: ISO date string — inclusive start of range.
        date_to: ISO date string — inclusive end of range.

    Returns:
        A dict with the keys:

        - **total_income** (*float*) — Sum of all income amounts.
        - **total_expense** (*float*) — Sum of all expense amounts.
        - **net** (*float*) — ``total_income - total_expense``.
        - **by_category** (*dict*) — ``{category_name: {total, count, type}}``.
        - **by_type** (*dict*) — ``{"Income": float, "Expense": float}``.
        - **entry_count** (*int*) — Number of entries in range.
    """
    entries = await get_financial_entries(
        date_from=date_from, date_to=date_to, limit=1000,
    )

    totals: dict[str, Any] = {
        "total_income": 0.0,
        "total_expense": 0.0,
        "net": 0.0,
        "by_category": {},
        "by_type": {"Income": 0.0, "Expense": 0.0},
        "entry_count": len(entries),
    }

    for entry in entries:
        t = entry["type"]
        signed = entry["signed_amount"]
        cat = entry["category"]
        abs_amt = abs(signed)

        if t == "Income":
            totals["total_income"] += abs_amt
        elif t == "Expense":
            totals["total_expense"] += abs_amt

        totals["by_type"][t] = totals["by_type"].get(t, 0.0) + signed

        if cat not in totals["by_category"]:
            totals["by_category"][cat] = {"total": 0.0, "count": 0, "type": t}
        totals["by_category"][cat]["total"] += abs_amt
        totals["by_category"][cat]["count"] += 1

    totals["net"] = totals["total_income"] - totals["total_expense"]
    return totals


# ──────────────────────────────────────────────
# Entry detail / lookup
# ──────────────────────────────────────────────


async def get_entry_detail(page_id: str) -> Dict[str, Any]:
    """
    Retrieve a single financial entry by page_id.

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
        all_entries = await get_financial_entries(
            date_from=month_ago, date_to=tomorrow, limit=250,
        )
        for e in all_entries:
            if e.get("page_id") == page_id:
                return {"found": True, "entry": e, "error": None}

        return {"found": False, "entry": None, "error": "Entry not found"}
    except Exception as e:
        logger.error("Failed to fetch entry %s: %s", page_id, e, exc_info=True)
        return {"found": False, "entry": None, "error": str(e)}


# ──────────────────────────────────────────────
# Delete / Archive
# ──────────────────────────────────────────────


async def delete_entry(page_id: str) -> Dict[str, Any]:
    """
    Archive (soft-delete) a financial entry in Notion.

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
        logger.info("Deleted financial entry: page_id=%s", page_id)
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


# ──────────────────────────────────────────────
# Update / Edit
# ──────────────────────────────────────────────


async def update_entry_type(page_id: str, new_type: str) -> Dict[str, Any]:
    """
    Update the transaction type of a financial entry.

    Updates the Type select property and rebuilds the Name title
    (``"NewType: Category — Amount"``) using the current entry's category
    and amount.

    Args:
        page_id: The Notion page ID of the entry.
        new_type: The new transaction type (``"Expense"`` or ``"Income"``).

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_type (str | None): The previous type.
            - new_type (str): The updated type.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_type": None,
            "new_type": new_type,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            return {
                "success": False,
                "old_type": None,
                "new_type": new_type,
                "page_id": page_id,
                "error": "Entry not found",
            }

        entry = detail["entry"]
        old_type = entry.get("type", "")
        category = entry.get("category", "")
        amount = entry.get("amount", 0.0)

        new_name = f"{new_type}: {category} — {amount}"
        await notion_manager.update_page(page_id, {
            "Name": NB.title(new_name),
            "Type": NB.select(new_type),
        })

        return {
            "success": True,
            "old_type": old_type,
            "new_type": new_type,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to update type for %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "old_type": None,
            "new_type": new_type,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_amount(page_id: str, new_amount: float) -> Dict[str, Any]:
    """
    Update the amount of a financial entry.

    Applies sign based on type (negative for expenses, positive for income).
    Also rebuilds the Name title (``"Type: Category — NewAmount"``).

    Args:
        page_id: The Notion page ID of the entry.
        new_amount: Positive transaction amount (sign applied automatically).

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_amount (float | None): The previous absolute amount.
            - new_amount (float): The updated absolute amount.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_amount": None,
            "new_amount": new_amount,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            return {
                "success": False,
                "old_amount": None,
                "new_amount": new_amount,
                "page_id": page_id,
                "error": "Entry not found",
            }

        entry = detail["entry"]
        old_amount = entry.get("amount", 0.0)
        type_ = entry.get("type", "")
        category = entry.get("category", "")

        sign = -1 if type_ == "Expense" else 1
        signed_amount = sign * new_amount

        new_name = f"{type_}: {category} — {new_amount}"
        await notion_manager.update_page(page_id, {
            "Name": NB.title(new_name),
            "Amount": NB.number(signed_amount),
        })

        return {
            "success": True,
            "old_amount": old_amount,
            "new_amount": new_amount,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to update amount for %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "old_amount": None,
            "new_amount": new_amount,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_category(page_id: str, new_category: str) -> Dict[str, Any]:
    """
    Update the category of a financial entry.

    Updates the Category select property and rebuilds the Name title
    (``"Type: NewCategory — Amount"``).

    Args:
        page_id: The Notion page ID of the entry.
        new_category: The new category name.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_category (str | None): The previous category.
            - new_category (str): The updated category.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_category": None,
            "new_category": new_category,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            return {
                "success": False,
                "old_category": None,
                "new_category": new_category,
                "page_id": page_id,
                "error": "Entry not found",
            }

        entry = detail["entry"]
        old_category = entry.get("category", "")
        type_ = entry.get("type", "")
        amount = entry.get("amount", 0.0)

        new_name = f"{type_}: {new_category} — {amount}"
        await notion_manager.update_page(page_id, {
            "Name": NB.title(new_name),
            "Category": NB.select(new_category),
        })

        return {
            "success": True,
            "old_category": old_category,
            "new_category": new_category,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to update category for %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "old_category": None,
            "new_category": new_category,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_date(page_id: str, new_date: str) -> Dict[str, Any]:
    """
    Update the date of a financial entry.

    Args:
        page_id: The Notion page ID of the entry.
        new_date: ISO 8601 date string.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_date (str | None): The previous date string.
            - new_date (str): The updated date string.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_date": None,
            "new_date": new_date,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            return {
                "success": False,
                "old_date": None,
                "new_date": new_date,
                "page_id": page_id,
                "error": "Entry not found",
            }

        entry = detail["entry"]
        old_date = entry.get("date", "")

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
        logger.error("Failed to update date for %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "old_date": None,
            "new_date": new_date,
            "page_id": page_id,
            "error": str(e),
        }


async def update_entry_notes(page_id: str, new_notes: str) -> Dict[str, Any]:
    """
    Update the notes of a financial entry.

    Args:
        page_id: The Notion page ID of the entry.
        new_notes: New notes text.

    Returns:
        A dict with keys:
            - success (bool): Whether the update succeeded.
            - old_notes (str | None): The previous notes text.
            - new_notes (str): The updated notes text.
            - page_id (str): The entry's page ID.
            - error (str | None): Error message if success is False.
    """
    if not page_id:
        return {
            "success": False,
            "old_notes": None,
            "new_notes": new_notes,
            "page_id": "",
            "error": "No page_id provided",
        }

    try:
        detail = await get_entry_detail(page_id)
        if not detail["found"] or not detail["entry"]:
            return {
                "success": False,
                "old_notes": None,
                "new_notes": new_notes,
                "page_id": page_id,
                "error": "Entry not found",
            }

        entry = detail["entry"]
        old_notes = entry.get("notes", "")

        await notion_manager.update_page(page_id, {
            "Notes": NB.rich_text(new_notes),
        })

        return {
            "success": True,
            "old_notes": old_notes,
            "new_notes": new_notes,
            "page_id": page_id,
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to update notes for %s: %s", page_id, e, exc_info=True)
        return {
            "success": False,
            "old_notes": None,
            "new_notes": new_notes,
            "page_id": page_id,
            "error": str(e),
        }


# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────

def _parse_financial_entry(page: dict[str, Any]) -> dict[str, Any] | None:
    """
    Parse a raw Notion page result into a clean financial entry dict.

    Returns ``None`` when critical fields are missing or parsing fails,
    allowing callers to silently skip malformed entries.
    """
    try:
        props = page.get("properties", {})

        # Name (title)
        title_parts = props.get("Name", {}).get("title", [])
        name = "".join(p.get("plain_text", "") for p in title_parts)

        # Type (select)
        type_prop = props.get("Type", {}).get("select")
        type_ = type_prop.get("name", "") if type_prop else ""

        # Amount (number, signed — negative for expenses)
        amount_raw = props.get("Amount", {}).get("number")
        signed_amount = float(amount_raw) if amount_raw is not None else 0.0

        # Category (select)
        cat_prop = props.get("Category", {}).get("select")
        category = cat_prop.get("name", "") if cat_prop else ""

        # Date
        date_prop = props.get("Date", {}).get("date")
        date_str = date_prop.get("start", "") if date_prop else ""

        # Notes (rich text)
        notes_parts = props.get("Notes", {}).get("rich_text", [])
        notes = "".join(p.get("plain_text", "") for p in notes_parts)

        return {
            "page_id": page.get("id", ""),
            "name": name,
            "type": type_,
            "amount": abs(signed_amount),
            "signed_amount": signed_amount,
            "category": category,
            "date": date_str,
            "notes": notes,
        }
    except Exception as e:
        logger.error("Failed to parse financial entry: %s", e)
        return None
