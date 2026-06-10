# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/financial.py

import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from config import settings
from notion.client import notion_manager
from notion.models import NotionPayloadBuilder as NB
from bot.keyboards import build_grid_keyboard, build_main_menu

logger = logging.getLogger(__name__)

# Conversation states
CHOOSE_TYPE, ENTER_AMOUNT, CHOOSE_CATEGORY, ENTER_NOTE = range(4)


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

    categories = await notion_manager.get_select_property_options(
        database_id=settings.DATABASE_ID_FINANCIAL_LOG,
        property_name="Category",
    )
    if not categories:
        categories = ["Food", "Transport", "Utilities", "Housing", "Entertainment", "Shopping", "Salary", "Other"]

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

    sign = -1 if tx_type == "Expense" else 1
    properties = {
        "Name": NB.title(f"{tx_type}: {category} — {amount}"),
        "Type": NB.select(tx_type),
        "Amount": NB.number(sign * amount),
        "Category": NB.select(category),
        "Date": NB.date(datetime.now(timezone.utc).isoformat()),
        "Notes": NB.rich_text(note),
    }

    try:
        await notion_manager.create_page(
            database_id=settings.DATABASE_ID_FINANCIAL_LOG,
            properties=properties,
        )
        success = f"Logged {tx_type}: {category} — {amount}"
    except Exception as e:
        logger.error(f"Failed to save financial entry: {e}")
        success = f"Error saving to Notion: {e}"

    reply_markup = build_main_menu()
    if update.callback_query:
        await update.callback_query.edit_message_text(success, reply_markup=reply_markup)
    elif status_msg:
        await status_msg.edit_text(success, reply_markup=reply_markup)

    return ConversationHandler.END
