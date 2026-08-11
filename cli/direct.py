"""
LifeOS CLI — Direct commands (no session state).

One-shot operations against the service layer.  Every command is stateless,
accepts ``--format toon|rich|text``, and write commands support ``--dry-run``.

Usage:
    lifeos direct activity --action log --type Work --start 2025-06-12T09:00 --desc "..."
    lifeos direct financial --action summary --days 30
    lifeos direct journal --journal-type subjective --action view --days 7
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import typer

from services import activity, financial, diet, journal
from cli.format import output as fmt_output

logger = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=5, minutes=30))

app = typer.Typer(help="Direct commands (no session state)")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(TZ).date().isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(TZ) - timedelta(days=days)).date().isoformat()


def _call_async(coro):
    """Bridge an async service call into a synchronous CLI command."""
    return asyncio.run(coro)


def _emit(data: dict, fmt: str) -> None:
    """Format and print output."""
    print(fmt_output(data, fmt))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Activity
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("activity")
def activity_cmd(
    action: str = typer.Option(..., help="log, view, gaps, stats, delete"),
    type: str = typer.Option(None, help="Activity type (for log)"),
    start: str = typer.Option(None, help="Start time ISO (for log)"),
    end: str = typer.Option(None, help="End time ISO (for log)"),
    desc: str = typer.Option(None, help="Description / notes (for log)"),
    page_id: str = typer.Option(None, help="Page ID (for delete)"),
    days: int = typer.Option(7, help="Days to look back"),
    format: str = typer.Option("toon", help="Output format: toon, rich, text"),
    dry_run: bool = typer.Option(False, help="Preview without saving"),
):
    """
    Activity log operations.

    Actions:
        log      – Save an activity entry (requires --type, --start).
        view     – Show recent entries.
        gaps     – Detect untracked gaps between entries.
        stats    – Summary statistics (48 h / 7 d / 30 d).
        delete   – Archive an entry by --page-id.
    """
    try:
        if action == "log":
            _activity_log(type, start, end, desc, dry_run, format)
        elif action == "view":
            _activity_view(days, format)
        elif action == "gaps":
            _activity_gaps(days, format)
        elif action == "stats":
            _activity_stats(format)
        elif action == "delete":
            _activity_delete(page_id, dry_run, format)
        else:
            _emit(
                {"error": f"Unknown action: {action}", "valid": ["log", "view", "gaps", "stats", "delete"]},
                format,
            )
    except Exception as exc:
        logger.exception("activity command failed")
        _emit({"error": str(exc)}, format)


def _activity_log(
    act_type: str | None,
    start_str: str | None,
    end_str: str | None,
    desc: str | None,
    dry_run: bool,
    format: str,
) -> None:
    if not act_type:
        _emit({"error": "--type is required for log"}, format)
        return
    if not start_str:
        _emit({"error": "--start is required for log"}, format)
        return

    start_dt = datetime.fromisoformat(start_str)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=TZ)

    end_dt: datetime | None = None
    if end_str:
        end_dt = datetime.fromisoformat(end_str)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=TZ)

    if dry_run:
        _emit(
            {
                "dry_run": True,
                "action": "log",
                "type": act_type,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat() if end_dt else None,
                "description": desc,
            },
            format,
        )
        return

    result = _call_async(
        activity.save_activity_entry(
            activity_type=act_type, start=start_dt, end=end_dt, notes=desc
        )
    )
    _emit(result, format)


def _activity_view(days: int, format: str) -> None:
    date_from = _days_ago_iso(days)
    date_to = _now_iso()
    entries = _call_async(
        activity.get_activity_entries(
            date_from=date_from, date_to=date_to, limit=50, sort_ascending=False
        )
    )
    _emit(
        {"entries": entries, "count": len(entries), "date_from": date_from, "date_to": date_to},
        format,
    )


def _activity_gaps(days: int, format: str) -> None:
    date_from = _days_ago_iso(days)
    date_to = _now_iso()
    entries = _call_async(
        activity.get_activity_entries(
            date_from=date_from, date_to=date_to, limit=200, sort_ascending=True
        )
    )
    now = datetime.now(TZ)
    window_start = now - timedelta(days=days)
    gaps = activity.get_gaps(entries, threshold_minutes=30, window_start=window_start, window_end=now)
    _emit(
        {"gaps": gaps, "gap_count": len(gaps), "total_unexplained_hrs": sum(g["hours"] for g in gaps)},
        format,
    )


def _activity_stats(format: str) -> None:
    stats = _call_async(activity.get_activity_stats(hours=48))
    _emit(stats, format)


def _activity_delete(page_id: str | None, dry_run: bool, format: str) -> None:
    if not page_id:
        _emit({"error": "--page-id is required for delete"}, format)
        return

    if dry_run:
        _emit({"dry_run": True, "action": "delete", "page_id": page_id}, format)
        return

    result = _call_async(activity.delete_entry(page_id=page_id))
    _emit(result, format)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Financial
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("financial")
def financial_cmd(
    action: str = typer.Option(..., help="log, view, summary, categories, detail, edit, delete"),
    type: str = typer.Option(None, help="Expense or Income"),
    amount: float = typer.Option(None, help="Transaction amount"),
    category: str = typer.Option(None, help="Category name"),
    notes: str = typer.Option(None, help="Optional notes"),
    page_id: str = typer.Option(None, help="Page ID (for detail/edit/delete)"),
    days: int = typer.Option(30, help="Look-back window in days"),
    format: str = typer.Option("toon", help="Output format: toon, rich, text"),
    dry_run: bool = typer.Option(False, help="Preview without saving"),
):
    """
    Financial log operations.

    Actions:
        log        – Save a financial entry (requires --type, --amount, --category).
        view       – Show recent transactions.
        summary    – Aggregated totals over the date range.
        categories – List available category options.
        detail     – Show entry details (requires --page-id).
        edit       – Interactively edit an entry (requires --page-id).
        delete     – Archive an entry (requires --page-id).
    """
    try:
        if action == "log":
            _financial_log(type, amount, category, notes, dry_run, format)
        elif action == "view":
            _financial_view(days, format)
        elif action == "summary":
            _financial_summary(days, format)
        elif action == "categories":
            _financial_categories(format)
        elif action == "detail":
            _financial_detail(page_id)
        elif action == "edit":
            _financial_edit(page_id)
        elif action == "delete":
            _financial_delete(page_id)
        else:
            _emit(
                {
                    "error": f"Unknown action: {action}",
                    "valid": ["log", "view", "summary", "categories", "detail", "edit", "delete"],
                },
                format,
            )
    except Exception as exc:
        logger.exception("financial command failed")
        _emit({"error": str(exc)}, format)


def _financial_log(
    type_: str | None,
    amount: float | None,
    category: str | None,
    notes: str | None,
    dry_run: bool,
    format: str,
) -> None:
    if not type_:
        _emit({"error": "--type (Expense/Income) is required"}, format)
        return
    if amount is None:
        _emit({"error": "--amount is required"}, format)
        return
    if not category:
        _emit({"error": "--category is required"}, format)
        return

    if dry_run:
        _emit(
            {
                "dry_run": True,
                "action": "log",
                "type": type_,
                "amount": amount,
                "category": category,
                "notes": notes or "",
            },
            format,
        )
        return

    result = _call_async(
        financial.save_financial_entry(
            type_=type_, amount=amount, category=category, notes=notes or ""
        )
    )
    _emit(result, format)


def _financial_view(days: int, format: str) -> None:
    date_from = _days_ago_iso(days)
    date_to = _now_iso()
    entries = _call_async(
        financial.get_financial_entries(date_from=date_from, date_to=date_to, limit=50)
    )
    _emit(
        {"entries": entries, "count": len(entries), "date_from": date_from, "date_to": date_to},
        format,
    )


def _financial_summary(days: int, format: str) -> None:
    date_from = _days_ago_iso(days)
    date_to = _now_iso()
    summary = _call_async(
        financial.get_financial_summary(date_from=date_from, date_to=date_to)
    )
    _emit(summary, format)


def _financial_categories(format: str) -> None:
    cats = _call_async(financial.get_financial_categories())
    _emit({"categories": cats, "count": len(cats)}, format)


def _financial_detail(page_id: str) -> None:
    """Display financial entry details."""
    result = _call_async(financial.get_entry_detail(page_id))
    if not result.get("found"):
        print(f"Entry not found: {result.get('error', 'unknown')}")
        return
    entry = result["entry"]
    print(f"💰 Type: {entry.get('type', 'N/A')}")
    print(f"📅 Date: {entry.get('date', 'N/A')}")
    print()
    print(f"📂 Category: {entry.get('category', 'N/A')}")
    print(f"💵 Amount: ${entry.get('amount', 0):.2f}")
    print()
    print(f"📝 Notes: {entry.get('notes', '')}")
    print(f"Page ID: {entry.get('page_id', '')}")


def _financial_edit(page_id: str) -> None:
    """Interactively edit a financial entry."""
    result = _call_async(financial.get_entry_detail(page_id))
    if not result.get("found"):
        print(f"Entry not found: {result.get('error', 'unknown')}")
        return
    entry = result["entry"]

    print("Current entry:")
    print(f"  1. Type: {entry.get('type', 'N/A')}")
    print(f"  2. Amount: ${entry.get('amount', 0):.2f}")
    print(f"  3. Category: {entry.get('category', 'N/A')}")
    print(f"  4. Date: {entry.get('date', 'N/A')}")
    print(f"  5. Notes: {entry.get('notes', '')}")
    print(f"  6. Cancel")

    choice = input("Choose field to edit (1-6): ").strip()

    if choice == "1":
        new_val = input("Enter new type (Expense/Income): ").strip()
        if new_val:
            result = _call_async(financial.update_entry_type(page_id, new_val))
            if result.get("success"):
                print(f"✅ Type updated: {result.get('old_type')} → {result.get('new_type')}")
            else:
                print(f"❌ Failed: {result.get('error', 'unknown')}")
    elif choice == "2":
        new_val = input("Enter new amount: ").strip()
        if new_val:
            try:
                new_amount = float(new_val.replace("$", ""))
                result = _call_async(financial.update_entry_amount(page_id, new_amount))
                if result.get("success"):
                    print(f"✅ Amount updated: ${result.get('old_amount', 0):.2f} → ${result.get('new_amount', 0):.2f}")
                else:
                    print(f"❌ Failed: {result.get('error', 'unknown')}")
            except ValueError:
                print("❌ Invalid amount.")
    elif choice == "3":
        new_val = input("Enter new category: ").strip()
        if new_val:
            result = _call_async(financial.update_entry_category(page_id, new_val))
            if result.get("success"):
                print(f"✅ Category updated: {result.get('old_category')} → {result.get('new_category')}")
            else:
                print(f"❌ Failed: {result.get('error', 'unknown')}")
    elif choice == "4":
        new_val = input("Enter new date (YYYY-MM-DD): ").strip()
        if new_val:
            result = _call_async(financial.update_entry_date(page_id, new_val))
            if result.get("success"):
                print(f"✅ Date updated: {result.get('old_date')} → {result.get('new_date')}")
            else:
                print(f"❌ Failed: {result.get('error', 'unknown')}")
    elif choice == "5":
        new_val = input("Enter new notes: ").strip()
        if new_val:
            result = _call_async(financial.update_entry_notes(page_id, new_val))
            if result.get("success"):
                print(f"✅ Notes updated: {result.get('old_notes')} → {result.get('new_notes')}")
            else:
                print(f"❌ Failed: {result.get('error', 'unknown')}")
    elif choice == "6":
        print("Cancelled.")
    else:
        print("Invalid choice.")


def _financial_delete(page_id: str) -> None:
    """Delete a financial entry with confirmation."""
    confirm = input(f"Are you sure you want to delete entry {page_id}? (y/N): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return
    result = _call_async(financial.delete_entry(page_id))
    if result.get("success"):
        print(f"✅ Entry {page_id} deleted.")
    else:
        print(f"❌ Failed to delete: {result.get('error', 'unknown')}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Diet
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("diet")
def diet_cmd(
    action: str = typer.Option(..., help="log, view, meals, detail, edit, delete"),
    meal_type: str = typer.Option(None, help="Breakfast, Lunch, Dinner, Snack"),
    description: str = typer.Option(None, help="What was eaten"),
    calories: int = typer.Option(None, help="Calorie count"),
    page_id: str = typer.Option(None, help="Page ID (for detail/edit/delete)"),
    days: int = typer.Option(7, help="Look-back window in days"),
    format: str = typer.Option("toon", help="Output format: toon, rich, text"),
    dry_run: bool = typer.Option(False, help="Preview without saving"),
):
    """
    Diet log operations.

    Actions:
        log    – Save a diet entry (requires --meal-type, --description).
        view   – Show recent meals.
        meals  – List available meal types.
        detail – Show entry details (requires --page-id).
        edit   – Interactively edit an entry (requires --page-id).
        delete – Archive an entry (requires --page-id).
    """
    try:
        if action == "log":
            _diet_log(meal_type, description, calories, dry_run, format)
        elif action == "view":
            _diet_view(days, format)
        elif action == "meals":
            _diet_meals(format)
        elif action == "detail":
            _diet_detail(page_id)
        elif action == "edit":
            _diet_edit(page_id)
        elif action == "delete":
            _diet_delete(page_id)
        else:
            _emit(
                {"error": f"Unknown action: {action}", "valid": ["log", "view", "meals", "detail", "edit", "delete"]},
                format,
            )
    except Exception as exc:
        logger.exception("diet command failed")
        _emit({"error": str(exc)}, format)


def _diet_log(
    meal_type: str | None,
    description: str | None,
    calories: int | None,
    dry_run: bool,
    format: str,
) -> None:
    if not meal_type:
        _emit({"error": "--meal-type is required"}, format)
        return
    if not description:
        _emit({"error": "--description is required"}, format)
        return

    if dry_run:
        _emit(
            {
                "dry_run": True,
                "action": "log",
                "meal_type": meal_type,
                "description": description,
                "calories": calories,
            },
            format,
        )
        return

    result = _call_async(
        diet.save_diet_entry(
            meal_type=meal_type,
            meal_description=description,
            notes="",
            calories=calories,
        )
    )
    _emit(result, format)


def _diet_view(days: int, format: str) -> None:
    date_from = _days_ago_iso(days)
    date_to = _now_iso()
    entries = _call_async(
        diet.get_diet_entries(date_from=date_from, date_to=date_to, limit=50)
    )
    _emit(
        {"entries": entries, "count": len(entries), "date_from": date_from, "date_to": date_to},
        format,
    )


def _diet_meals(format: str) -> None:
    meals = _call_async(diet.get_meal_types())
    _emit({"meal_types": meals, "count": len(meals)}, format)


def _diet_detail(page_id: str) -> None:
    """Display diet entry details."""
    result = _call_async(diet.get_entry_detail(page_id))
    if not result.get("found"):
        print(f"Entry not found: {result.get('error', 'unknown')}")
        return
    entry = result["entry"]
    print(f"🍽️ Meal Type: {entry.get('meal_type', 'N/A')}")
    print(f"📅 Date: {entry.get('date', 'N/A')}")
    print()
    print(f"📝 Description: {entry.get('description', 'N/A')}")
    print(f"🔢 Calories: {entry.get('calories', 'N/A')}")
    print()
    print(f"📝 Notes: {entry.get('notes', '')}")
    print(f"Page ID: {entry.get('page_id', '')}")


def _diet_edit(page_id: str) -> None:
    """Interactively edit a diet entry."""
    result = _call_async(diet.get_entry_detail(page_id))
    if not result.get("found"):
        print(f"Entry not found: {result.get('error', 'unknown')}")
        return
    entry = result["entry"]

    print("Current entry:")
    print(f"  1. Meal Type: {entry.get('meal_type', 'N/A')}")
    print(f"  2. Description: {entry.get('description', 'N/A')}")
    print(f"  3. Calories: {entry.get('calories', 'N/A')}")
    print(f"  4. Date: {entry.get('date', 'N/A')}")
    print(f"  5. Cancel")

    choice = input("Choose field to edit (1-5): ").strip()

    if choice == "1":
        new_val = input("Enter new meal type: ").strip()
        if new_val:
            result = _call_async(diet.update_entry_meal_type(page_id, new_val))
            if result.get("success"):
                print(f"✅ Meal type updated: {result.get('old_type')} → {result.get('new_type')}")
            else:
                print(f"❌ Failed: {result.get('error', 'unknown')}")
    elif choice == "2":
        new_val = input("Enter new description: ").strip()
        if new_val:
            result = _call_async(diet.update_entry_description(page_id, new_val))
            if result.get("success"):
                print(f"✅ Description updated: {result.get('old_desc')} → {result.get('new_desc')}")
            else:
                print(f"❌ Failed: {result.get('error', 'unknown')}")
    elif choice == "3":
        new_val = input("Enter new calories: ").strip()
        if new_val:
            try:
                result = _call_async(diet.update_entry_calories(page_id, int(new_val)))
                if result.get("success"):
                    print(f"✅ Calories updated: {result.get('old_calories')} → {result.get('new_calories')}")
                else:
                    print(f"❌ Failed: {result.get('error', 'unknown')}")
            except ValueError:
                print("❌ Invalid calorie value.")
    elif choice == "4":
        new_val = input("Enter new date (YYYY-MM-DD): ").strip()
        if new_val:
            result = _call_async(diet.update_entry_date(page_id, new_val))
            if result.get("success"):
                print(f"✅ Date updated: {result.get('old_date')} → {result.get('new_date')}")
            else:
                print(f"❌ Failed: {result.get('error', 'unknown')}")
    elif choice == "5":
        print("Cancelled.")
    else:
        print("Invalid choice.")


def _diet_delete(page_id: str) -> None:
    """Delete a diet entry with confirmation."""
    confirm = input(f"Are you sure you want to delete entry {page_id}? (y/N): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return
    result = _call_async(diet.delete_entry(page_id))
    if result.get("success"):
        print(f"✅ Entry {page_id} deleted.")
    else:
        print(f"❌ Failed to delete: {result.get('error', 'unknown')}")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Journal
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("journal")
def journal_cmd(
    journal_type: str = typer.Option(..., help="subjective, relational, systemic"),
    action: str = typer.Option("log", help="log, view"),
    # Subjective fields
    energy: int = typer.Option(None, help="Energy rating 1-10 (subjective)"),
    focus: int = typer.Option(None, help="Focus rating 1-10 (subjective)"),
    happiness: int = typer.Option(None, help="Happiness rating 1-10 (subjective)"),
    gratitude: str = typer.Option(None, help="Gratitude entry (subjective)"),
    # Relational fields
    person: str = typer.Option(None, help="Person name (relational)"),
    quality: int = typer.Option(None, help="Connection quality 1-10 (relational)"),
    insights: str = typer.Option(None, help="Relational insights text"),
    # Systemic fields
    bottlenecks: str = typer.Option(None, help="Systemic bottlenecks"),
    actions: str = typer.Option(None, help="Actionable items (systemic)"),
    # Common
    days: int = typer.Option(7, help="Look-back window in days"),
    format: str = typer.Option("toon", help="Output format: toon, rich, text"),
    dry_run: bool = typer.Option(False, help="Preview without saving"),
):
    """
    Journal operations for subjective, relational, and systemic journals.

    Examples:
        lifeos direct journal --journal-type subjective --action log --energy 7 --focus 8 --gratitude "Sunny day"
        lifeos direct journal --journal-type relational --action log --person "Alice" --quality 8 --insights "Great talk"
        lifeos direct journal --journal-type systemic --action log --bottlenecks "Focus" --actions "Meditate"
        lifeos direct journal --journal-type subjective --action view --days 14
    """
    valid_types = ("subjective", "relational", "systemic")
    if journal_type not in valid_types:
        _emit(
            {"error": f"Invalid journal_type: {journal_type}", "valid": list(valid_types)},
            format,
        )
        return

    j_opts = {
        "energy": energy,
        "focus": focus,
        "happiness": happiness,
        "gratitude": gratitude or "",
        "person": person,
        "quality": quality,
        "insights": insights or "",
        "bottlenecks": bottlenecks or "",
        "actions": actions or "",
    }

    try:
        if action == "log":
            _journal_log(journal_type, dry_run, format, j_opts)
        elif action == "view":
            _journal_view(journal_type, days, format)
        else:
            _emit(
                {"error": f"Unknown action: {action}", "valid": ["log", "view"]},
                format,
            )
    except Exception as exc:
        logger.exception("journal command failed")
        _emit({"error": str(exc)}, format)


def _journal_log(journal_type: str, dry_run: bool, format: str, opts: dict) -> None:
    if journal_type == "subjective":
        _journal_log_subjective(dry_run, format, opts)
    elif journal_type == "relational":
        _journal_log_relational(dry_run, format, opts)
    elif journal_type == "systemic":
        _journal_log_systemic(dry_run, format, opts)


def _journal_log_subjective(dry_run: bool, format: str, opts: dict) -> None:
    if dry_run:
        _emit(
            {
                "dry_run": True,
                "journal_type": "subjective",
                "energy": opts.get("energy"),
                "focus": opts.get("focus"),
                "happiness": opts.get("happiness"),
                "gratitude": opts.get("gratitude", ""),
            },
            format,
        )
        return

    result = _call_async(
        journal.save_subjective_entry(
            energy=opts.get("energy"),
            focus=opts.get("focus"),
            happiness=opts.get("happiness"),
            gratitude=opts.get("gratitude", ""),
        )
    )
    _emit(result, format)


def _journal_log_relational(dry_run: bool, format: str, opts: dict) -> None:
    person = opts.get("person")
    if not person:
        _emit({"error": "--person is required for relational journal"}, format)
        return

    if dry_run:
        _emit(
            {
                "dry_run": True,
                "journal_type": "relational",
                "person": person,
                "quality": opts.get("quality"),
                "insights": opts.get("insights", ""),
            },
            format,
        )
        return

    result = _call_async(
        journal.save_relational_entry(
            person=person,
            connection_quality=opts.get("quality"),
            insights=opts.get("insights", ""),
        )
    )
    _emit(result, format)


def _journal_log_systemic(dry_run: bool, format: str, opts: dict) -> None:
    if dry_run:
        _emit(
            {
                "dry_run": True,
                "journal_type": "systemic",
                "bottlenecks": opts.get("bottlenecks", ""),
                "actions": opts.get("actions", ""),
            },
            format,
        )
        return

    result = _call_async(
        journal.save_systemic_entry(
            bottlenecks=opts.get("bottlenecks", ""),
            actionable_items=opts.get("actions", ""),
        )
    )
    _emit(result, format)


def _journal_view(journal_type: str, days: int, format: str) -> None:
    date_from = _days_ago_iso(days)
    date_to = _now_iso()

    if journal_type == "subjective":
        entries = _call_async(
            journal.get_subjective_entries(date_from=date_from, date_to=date_to, limit=50)
        )
    elif journal_type == "relational":
        entries = _call_async(
            journal.get_relational_entries(date_from=date_from, date_to=date_to, limit=50)
        )
    else:
        entries = _call_async(
            journal.get_systemic_entries(date_from=date_from, date_to=date_to, limit=50)
        )

    _emit(
        {"entries": entries, "count": len(entries), "date_from": date_from, "date_to": date_to},
        format,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI entry point (if run directly)
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app()
