# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/diet.py

import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CallbackQueryHandler, MessageHandler, filters,
)
from services.diet import (
    get_meal_types, save_diet_entry,
    get_entry_detail, delete_entry,
    update_entry_meal_type, update_entry_description,
    update_entry_calories, update_entry_date,
)
from bot.keyboards import (
    build_grid_keyboard, build_main_menu,
    diet_entry_detail_keyboard, diet_edit_field_keyboard,
)

logger = logging.getLogger(__name__)

# Conversation states
CHOOSE_MEAL, ENTER_DESCRIPTION, ENTER_CALORIES, ENTER_NOTE = range(4)

# Edit conversation states
DIET_EDIT_DESCRIPTION, DIET_EDIT_CALORIES, DIET_EDIT_DATE = range(4, 7)


async def start_diet_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: choose meal type."""
    query = update.callback_query
    await query.answer()

    meals = await get_meal_types()

    keyboard = build_grid_keyboard(meals, "diet_meal")
    await query.edit_message_text("Select meal type:", reply_markup=keyboard)
    return CHOOSE_MEAL


async def meal_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles meal type selection, prompts for description."""
    query = update.callback_query
    await query.answer()

    meal = query.data.split(":", 1)[1]
    context.user_data["diet_meal"] = meal

    await query.edit_message_text(f"Meal: {meal}\nDescribe what you ate:")
    return ENTER_DESCRIPTION


async def description_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles food description, prompts for optional calories."""
    context.user_data["diet_description"] = update.message.text.strip()

    await update.message.reply_text(
        "Enter calories (or press Skip):",
        reply_markup=build_grid_keyboard(["Skip"], "diet_cal"),
    )
    return ENTER_CALORIES


async def skip_calories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles Skip button for calories."""
    query = update.callback_query
    await query.answer()
    context.user_data["diet_calories"] = None
    return await _prompt_note(update, context)


async def calories_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validates calorie entry."""
    text = update.message.text.strip()
    try:
        cals = int(text)
        if cals < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid non-negative number for calories:")
        return ENTER_CALORIES

    context.user_data["diet_calories"] = cals
    return await _prompt_note(update, context)


async def _prompt_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompts for optional note."""
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Enter a note (or press Skip):",
            reply_markup=build_grid_keyboard(["Skip"], "diet_note"),
        )
    else:
        await update.message.reply_text(
            "Enter a note (or press Skip):",
            reply_markup=build_grid_keyboard(["Skip"], "diet_note"),
        )
    return ENTER_NOTE


async def skip_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles Skip button for notes."""
    query = update.callback_query
    await query.answer()
    context.user_data["diet_note"] = ""
    return await _save_diet(update, context)


async def note_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles free-text note entry."""
    context.user_data["diet_note"] = update.message.text.strip()
    return await _save_diet(update, context)


async def _save_diet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the diet log entry via the service layer."""
    meal = context.user_data.get("diet_meal", "Snack")
    description = context.user_data.get("diet_description", "")
    calories = context.user_data.get("diet_calories")
    note = context.user_data.get("diet_note", "")

    status_msg = None
    if update.callback_query:
        await update.callback_query.edit_message_text("Saving to Notion...")
    elif update.message:
        status_msg = await update.message.reply_text("Saving to Notion...")

    result = await save_diet_entry(
        meal_type=meal,
        meal_description=description,
        notes=note,
        calories=calories,
    )

    success = result.get("message", "Diet entry logged.")
    if not result.get("success", False):
        logger.error(f"Failed to save diet entry: {success}")

    reply_markup = build_main_menu()
    if update.callback_query:
        await update.callback_query.edit_message_text(success, reply_markup=reply_markup)
    elif status_msg:
        await status_msg.edit_text(success, reply_markup=reply_markup)

    return ConversationHandler.END


# ── Entry Detail ──────────────────────────────────────────────────────────────


async def diet_entry_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show diet entry detail with edit/delete options."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]

    detail_result = await get_entry_detail(page_id)
    if not detail_result["found"] or not detail_result["entry"]:
        await query.edit_message_text("Entry not found.")
        return

    entry = detail_result["entry"]
    context.user_data["diet_edit_entry"] = entry
    context.user_data["diet_edit_page_id"] = page_id

    meal_type = entry.get("meal_type", "")
    date_str = entry.get("date", "")
    description = entry.get("description", "")
    notes = entry.get("notes", "")
    calories = entry.get("calories")

    # Format date for display
    try:
        dt = datetime.fromisoformat(date_str)
        display_date = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        display_date = date_str

    text = f"🍽️ *{meal_type}*\n📅 {display_date}\n\n{description}"
    if notes:
        text += f"\n\n📝 {notes}"
    if calories is not None:
        text += f"\n🔢 {calories} cal"

    await query.edit_message_text(text, reply_markup=diet_entry_detail_keyboard(page_id))


# ── Edit Type ─────────────────────────────────────────────────────────────────


async def diet_edit_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show meal type selection keyboard."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["diet_edit_page_id"] = page_id

    await query.edit_message_text(
        "Select new meal type:",
        reply_markup=diet_edit_field_keyboard(page_id, "meal_type"),
    )


async def diet_set_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update meal type of a diet entry."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    page_id = parts[1]
    new_type = parts[2]

    result = await update_entry_meal_type(page_id, new_type)
    if result["success"]:
        await query.edit_message_text(f"✅ Meal type updated to {new_type}.")
    else:
        logger.error(f"Failed to update meal type: {result.get('error')}")
        await query.edit_message_text(f"Error: {result.get('error', 'Unknown error')}")


# ── Edit Description (text input) ────────────────────────────────────────────


async def diet_edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new description text."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["diet_edit_page_id"] = page_id

    await query.edit_message_text(
        "Enter new description:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return DIET_EDIT_DESCRIPTION


async def diet_handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new description text from user."""
    new_desc = update.message.text.strip()
    page_id = context.user_data.get("diet_edit_page_id", "")

    status_msg = await update.message.reply_text("Updating...")
    result = await update_entry_description(page_id, new_desc)

    if result["success"]:
        await status_msg.edit_text("✅ Description updated.")
    else:
        logger.error(f"Failed to update description: {result.get('error')}")
        await status_msg.edit_text(f"Error: {result.get('error', 'Unknown error')}")

    return ConversationHandler.END


# ── Edit Calories (text input) ───────────────────────────────────────────────


async def diet_edit_calories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new calorie count."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["diet_edit_page_id"] = page_id

    await query.edit_message_text(
        "Enter new calorie count:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return DIET_EDIT_CALORIES


async def diet_handle_calories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new calorie count from user."""
    text = update.message.text.strip()
    page_id = context.user_data.get("diet_edit_page_id", "")

    try:
        cals = int(text)
        if cals < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid non-negative number for calories:")
        return DIET_EDIT_CALORIES

    status_msg = await update.message.reply_text("Updating...")
    result = await update_entry_calories(page_id, cals)

    if result["success"]:
        await status_msg.edit_text(f"✅ Calories updated to {cals}.")
    else:
        logger.error(f"Failed to update calories: {result.get('error')}")
        await status_msg.edit_text(f"Error: {result.get('error', 'Unknown error')}")

    return ConversationHandler.END


# ── Edit Date (text input) ───────────────────────────────────────────────────


async def diet_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt for new date."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["diet_edit_page_id"] = page_id

    await query.edit_message_text(
        "Enter new date (YYYY-MM-DD):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return DIET_EDIT_DATE


async def diet_handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle new date from user."""
    date_str = update.message.text.strip()
    page_id = context.user_data.get("diet_edit_page_id", "")

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Please enter a valid date in YYYY-MM-DD format:")
        return DIET_EDIT_DATE

    status_msg = await update.message.reply_text("Updating...")
    result = await update_entry_date(page_id, date_str)

    if result["success"]:
        await status_msg.edit_text(f"✅ Date updated to {date_str}.")
    else:
        logger.error(f"Failed to update date: {result.get('error')}")
        await status_msg.edit_text(f"Error: {result.get('error', 'Unknown error')}")

    return ConversationHandler.END


# ── Delete Entry ─────────────────────────────────────────────────────────────


async def diet_entry_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a diet entry."""
    query = update.callback_query
    await query.answer("Deleting...")

    page_id = query.data.split(":", 1)[1]

    result = await delete_entry(page_id)
    if result["success"]:
        await query.edit_message_text("🗑 Entry deleted.", reply_markup=ReplyKeyboardRemove())
    else:
        logger.error(f"Failed to delete entry: {result.get('error')}")
        await query.edit_message_text(f"Error: {result.get('error', 'Unknown error')}")


# ── Cancel Handlers ──────────────────────────────────────────────────────────


async def diet_entry_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel edit via inline button callback."""
    query = update.callback_query
    await query.answer("Edit cancelled")
    await query.edit_message_text("Edit cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def diet_entry_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel edit via /cancel command."""
    await update.message.reply_text("Edit cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Edit ConversationHandler ─────────────────────────────────────────────────


diet_edit_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(diet_edit_description, pattern=r"^diet_edit_desc:"),
        CallbackQueryHandler(diet_edit_calories, pattern=r"^diet_edit_calories:"),
        CallbackQueryHandler(diet_edit_date, pattern=r"^diet_edit_date:"),
    ],
    states={
        DIET_EDIT_DESCRIPTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diet_handle_description),
        ],
        DIET_EDIT_CALORIES: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diet_handle_calories),
        ],
        DIET_EDIT_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diet_handle_date),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(diet_entry_cancel, pattern=r"^diet_cancel_edit:"),
        MessageHandler(filters.COMMAND | filters.Regex(r"^/cancel$"), diet_entry_cancel_cmd),
    ],
    map_to_parent={ConversationHandler.END: ConversationHandler.END},
    per_user=True,
    per_chat=True,
)
