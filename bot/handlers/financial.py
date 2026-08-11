# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/financial.py

import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from bot.keyboards import build_grid_keyboard, build_main_menu, financial_entry_detail_keyboard, financial_edit_field_keyboard
from services.financial import save_financial_entry, get_financial_categories
import services.financial as svc_financial

logger = logging.getLogger(__name__)

# ── Add transaction conversation states ──
CHOOSE_TYPE, ENTER_AMOUNT, CHOOSE_CATEGORY, ENTER_NOTE = range(4)

# ── Edit entry conversation states ──
FIN_EDIT_AMOUNT, FIN_EDIT_CATEGORY, FIN_EDIT_DATE, FIN_EDIT_NOTES = range(4, 8)


async def start_financial_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: choose transaction type."""
    query = update.callback_query
    await query.answer()

    types = ["Expense", "Income"]
    keyboard = build_grid_keyboard(types, "fin_type")
    await query.edit_message_text("Select transaction type:", reply_markup=keyboard)
    return CHOOSE_TYPE


async def type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles type selection, prompts for amount."""
    query = update.callback_query
    await query.answer()

    tx_type = query.data.split(":", 1)[1]
    context.user_data["fin_type"] = tx_type

    await query.edit_message_text(f"Type: {tx_type}\nEnter the amount (e.g. 42.50):")
    return ENTER_AMOUNT


async def amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validates amount and shows category buttons."""
    text = update.message.text.strip()
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid positive amount:")
        return ENTER_AMOUNT

    context.user_data["fin_amount"] = amount

    categories = await get_financial_categories()

    keyboard = build_grid_keyboard(categories, "fin_cat")
    await update.message.reply_text(
        f"Amount: {amount}\nSelect a category:",
        reply_markup=keyboard,
    )
    return CHOOSE_CATEGORY


async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles category selection, prompts for optional note."""
    query = update.callback_query
    await query.answer()

    category = query.data.split(":", 1)[1]
    context.user_data["fin_category"] = category

    await query.edit_message_text(
        f"Category: {category}\nEnter a note (or press Skip):",
        reply_markup=build_grid_keyboard(["Skip"], "fin_note"),
    )
    return ENTER_NOTE


async def skip_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles Skip button for notes."""
    query = update.callback_query
    await query.answer()
    context.user_data["fin_note"] = ""
    return await _save_financial(update, context)


async def note_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles free-text note entry."""
    context.user_data["fin_note"] = update.message.text.strip()
    return await _save_financial(update, context)


async def _save_financial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Constructs the Notion payload and saves the financial log entry."""
    tx_type = context.user_data.get("fin_type", "Expense")
    amount = context.user_data.get("fin_amount", 0)
    category = context.user_data.get("fin_category", "Other")
    note = context.user_data.get("fin_note", "")

    status_msg = None
    if update.callback_query:
        await update.callback_query.edit_message_text("Saving to Notion...")
    elif update.message:
        status_msg = await update.message.reply_text("Saving to Notion...")

    result = await save_financial_entry(
        type_=tx_type,
        amount=amount,
        category=category,
        notes=note,
    )

    if result["success"]:
        success = f"Logged {tx_type}: {category} — {amount}"
    else:
        logger.error(f"Failed to save financial entry: {result['error']}")
        success = f"Error saving to Notion: {result['error']}"

    reply_markup = build_main_menu()
    if update.callback_query:
        await update.callback_query.edit_message_text(success, reply_markup=reply_markup)
    elif status_msg:
        await status_msg.edit_text(success, reply_markup=reply_markup)

    return ConversationHandler.END


# ── Entry Detail ──────────────────────────────────────────────────────────────

async def financial_entry_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show financial entry detail with edit/delete options."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    result = await svc_financial.get_entry_detail(page_id)

    if not result["found"] or not result["entry"]:
        await query.edit_message_text("Entry not found.")
        return

    entry = result["entry"]
    text = (
        f"💰 <b>{entry['type']}</b>\n"
        f"📅 {entry['date']}\n\n"
        f"{entry['category']}: ${entry['amount']:.2f}"
    )
    if entry.get("notes"):
        text += f"\n\n📝 {entry['notes']}"

    await query.edit_message_text(text, reply_markup=financial_entry_detail_keyboard(page_id))


# ── Edit Type (inline buttons) ────────────────────────────────────────────────

async def financial_edit_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show type selection buttons for editing."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    await query.edit_message_text(
        "Select new type:",
        reply_markup=financial_edit_field_keyboard(page_id, "type"),
    )


async def financial_set_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle type selection from the type edit keyboard."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    page_id = parts[1]
    new_type = parts[2]

    result = await svc_financial.update_entry_type(page_id, new_type)
    if result["success"]:
        await query.answer(f"Type updated to {new_type}!")
        await query.edit_message_text(
            f"Type updated to {new_type}.",
            reply_markup=financial_entry_detail_keyboard(page_id),
        )
    else:
        logger.error(f"Failed to update type: {result['error']}")
        await query.answer(f"Error: {result['error']}", show_alert=True)


# ── Edit Amount (text prompt → conversation) ─────────────────────────────────

async def financial_edit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new amount, transition to FIN_EDIT_AMOUNT."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["financial_edit_page_id"] = page_id
    await query.edit_message_text("Enter new amount:")
    return FIN_EDIT_AMOUNT


async def financial_handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate and save the new amount."""
    text = update.message.text.strip()
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid positive number:")
        return FIN_EDIT_AMOUNT

    page_id = context.user_data.get("financial_edit_page_id", "")
    result = await svc_financial.update_entry_amount(page_id, amount)

    if result["success"]:
        await update.message.reply_text(
            f"Amount updated to ${amount:.2f}.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        logger.error(f"Failed to update amount: {result['error']}")
        await update.message.reply_text(
            f"Error: {result['error']}",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


# ── Edit Category (text prompt → conversation) ───────────────────────────────

async def financial_edit_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new category, transition to FIN_EDIT_CATEGORY."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["financial_edit_page_id"] = page_id
    await query.edit_message_text("Enter new category:")
    return FIN_EDIT_CATEGORY


async def financial_handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the new category."""
    category = update.message.text.strip()
    page_id = context.user_data.get("financial_edit_page_id", "")
    result = await svc_financial.update_entry_category(page_id, category)

    if result["success"]:
        await update.message.reply_text(
            f"Category updated to {category}.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        logger.error(f"Failed to update category: {result['error']}")
        await update.message.reply_text(
            f"Error: {result['error']}",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


# ── Edit Date (text prompt → conversation) ───────────────────────────────────

async def financial_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new date, transition to FIN_EDIT_DATE."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["financial_edit_page_id"] = page_id
    await query.edit_message_text("Enter new date (YYYY-MM-DD):")
    return FIN_EDIT_DATE


async def financial_handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate and save the new date."""
    date_str = update.message.text.strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Please enter a valid date (YYYY-MM-DD):")
        return FIN_EDIT_DATE

    page_id = context.user_data.get("financial_edit_page_id", "")
    result = await svc_financial.update_entry_date(page_id, date_str)

    if result["success"]:
        await update.message.reply_text(
            f"Date updated to {date_str}.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        logger.error(f"Failed to update date: {result['error']}")
        await update.message.reply_text(
            f"Error: {result['error']}",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


# ── Edit Notes (text prompt → conversation) ──────────────────────────────────

async def financial_edit_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new notes, transition to FIN_EDIT_NOTES."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["financial_edit_page_id"] = page_id
    await query.edit_message_text("Enter new notes:")
    return FIN_EDIT_NOTES


async def financial_handle_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the new notes."""
    notes = update.message.text.strip()
    page_id = context.user_data.get("financial_edit_page_id", "")
    result = await svc_financial.update_entry_notes(page_id, notes)

    if result["success"]:
        await update.message.reply_text(
            "Notes updated.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        logger.error(f"Failed to update notes: {result['error']}")
        await update.message.reply_text(
            f"Error: {result['error']}",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


# ── Delete Entry ──────────────────────────────────────────────────────────────

async def financial_entry_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a financial entry."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    result = await svc_financial.delete_entry(page_id)

    if result["success"]:
        await query.edit_message_text("Entry deleted.")
    else:
        logger.error(f"Failed to delete entry: {result['error']}")
        await query.edit_message_text(f"Error: {result['error']}")


# ── Cancel handlers ──────────────────────────────────────────────────────────

async def financial_entry_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel edit from a callback button."""
    query = update.callback_query
    await query.answer("Edit cancelled")
    await query.edit_message_text("Edit cancelled.")
    return ConversationHandler.END


async def financial_entry_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel edit from a /cancel command."""
    await update.message.reply_text("Edit cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Edit Conversation Handler ─────────────────────────────────────────────────

financial_edit_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(financial_edit_amount, pattern=r"^fin_edit_amount:"),
        CallbackQueryHandler(financial_edit_category, pattern=r"^fin_edit_category:"),
        CallbackQueryHandler(financial_edit_date, pattern=r"^fin_edit_date:"),
        CallbackQueryHandler(financial_edit_notes, pattern=r"^fin_edit_notes:"),
    ],
    states={
        FIN_EDIT_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, financial_handle_amount),
        ],
        FIN_EDIT_CATEGORY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, financial_handle_category),
        ],
        FIN_EDIT_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, financial_handle_date),
        ],
        FIN_EDIT_NOTES: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, financial_handle_notes),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(financial_entry_cancel, pattern=r"^fin_cancel_edit:"),
        MessageHandler(filters.COMMAND | filters.Regex(r"^/cancel$"), financial_entry_cancel_cmd),
    ],
    map_to_parent={ConversationHandler.END: ConversationHandler.END},
    per_user=True,
    per_chat=True,
)
