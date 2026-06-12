# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/diet.py

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from services.diet import get_meal_types, save_diet_entry
from bot.keyboards import build_grid_keyboard, build_main_menu

logger = logging.getLogger(__name__)

# Conversation states
CHOOSE_MEAL, ENTER_DESCRIPTION, ENTER_CALORIES, ENTER_NOTE = range(4)


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
