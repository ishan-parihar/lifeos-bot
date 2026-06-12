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
from datetime import datetime, timezone
from typing import Any

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
        - **data** (*dict | None*) — Saved entry metadata on success.
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
        await notion_manager.create_page(
            database_id=settings.DATABASE_ID_FINANCIAL_LOG,
            properties=properties,
        )
        return {
            "success": True,
            "data": {"type": type_, "category": category, "amount": amount, "date": date},
            "error": None,
        }
    except Exception as e:
        logger.error("Failed to save financial entry: %s", e)
        return {"success": False, "data": None, "error": str(e)}


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
