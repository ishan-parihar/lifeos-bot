# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/journal.py

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from services.journal import save_subjective_entry, get_subjective_entries, save_relational_entry, get_relational_entries, save_systemic_entry, get_systemic_entries
from bot.keyboards import build_grid_keyboard, build_number_keyboard, build_main_menu

logger = logging.getLogger(__name__)

# ── Subjective Journal ─────────────────────────────────────────────────────────
SUBJ_ENERGY, SUBJ_FOCUS, SUBJ_HAPPINESS, SUBJ_GRATITUDE = range(4)


async def start_subjective_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Rate your energy (1-10):", reply_markup=build_number_keyboard("subj_energy"))
    return SUBJ_ENERGY


async def subjective_energy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = query.data.split(":", 1)[1]
    context.user_data["subj_energy"] = int(val) if val != "skip" else None
    await query.edit_message_text("Rate your focus (1-10):", reply_markup=build_number_keyboard("subj_focus"))
    return SUBJ_FOCUS


async def subjective_focus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = query.data.split(":", 1)[1]
    context.user_data["subj_focus"] = int(val) if val != "skip" else None
    await query.edit_message_text("Rate your happiness (1-10):", reply_markup=build_number_keyboard("subj_happiness"))
    return SUBJ_HAPPINESS


async def subjective_happiness(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = query.data.split(":", 1)[1]
    context.user_data["subj_happiness"] = int(val) if val != "skip" else None
    await query.edit_message_text(
        "What are you grateful for today?\n(Type or press Skip):",
        reply_markup=build_grid_keyboard(["Skip"], "subj_grat"),
    )
    return SUBJ_GRATITUDE


async def subjective_skip_gratitude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["subj_gratitude"] = ""
    return await _save_subjective(update, context)


async def subjective_gratitude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["subj_gratitude"] = update.message.text.strip()
    return await _save_subjective(update, context)


async def _save_subjective(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    energy = context.user_data.get("subj_energy")
    focus = context.user_data.get("subj_focus")
    happiness = context.user_data.get("subj_happiness")
    gratitude = context.user_data.get("subj_gratitude", "")

    if update.callback_query:
        await update.callback_query.edit_message_text("Saving to Notion...")
    elif update.message:
        status_msg = await update.message.reply_text("Saving to Notion...")

    result = await save_subjective_entry(energy=energy, focus=focus, happiness=happiness, gratitude=gratitude)

    reply_markup = build_main_menu()
    msg = result["message"] if result["success"] else f"Error: {result['message']}"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup)
    else:
        await status_msg.edit_text(msg, reply_markup=reply_markup)
    return ConversationHandler.END


# ── Relational Journal ─────────────────────────────────────────────────────────
REL_PERSON, REL_QUALITY, REL_INSIGHTS = range(4, 7)


async def start_relational_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Who did you interact with? (type a name):")
    return REL_PERSON


async def relational_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["rel_person"] = update.message.text.strip()
    await update.message.reply_text(
        "Rate the connection quality (1-10):",
        reply_markup=build_number_keyboard("rel_quality"),
    )
    return REL_QUALITY


async def relational_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = query.data.split(":", 1)[1]
    context.user_data["rel_quality"] = int(val) if val != "skip" else None
    await query.edit_message_text(
        "Any insights from this interaction?\n(Type or press Skip):",
        reply_markup=build_grid_keyboard(["Skip"], "rel_insights"),
    )
    return REL_INSIGHTS


async def relational_skip_insights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["rel_insights"] = ""
    return await _save_relational(update, context)


async def relational_insights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["rel_insights"] = update.message.text.strip()
    return await _save_relational(update, context)


async def _save_relational(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    person = context.user_data.get("rel_person", "Unknown")
    quality = context.user_data.get("rel_quality")
    insights = context.user_data.get("rel_insights", "")

    if update.callback_query:
        await update.callback_query.edit_message_text("Saving to Notion...")
    elif update.message:
        status_msg = await update.message.reply_text("Saving to Notion...")

    result = await save_relational_entry(person=person, connection_quality=quality, insights=insights)

    reply_markup = build_main_menu()
    msg = result["message"] if result["success"] else f"Error: {result['message']}"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup)
    else:
        await status_msg.edit_text(msg, reply_markup=reply_markup)
    return ConversationHandler.END


# ── Systemic Journal ───────────────────────────────────────────────────────────
SYS_BOTTLENECKS, SYS_ACTIONS = range(7, 9)


async def start_systemic_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("What are your current bottlenecks or friction points?")
    return SYS_BOTTLENECKS


async def systemic_bottlenecks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sys_bottlenecks"] = update.message.text.strip()
    await update.message.reply_text("What actionable changes or solutions can you try?")
    return SYS_ACTIONS


async def systemic_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sys_actions"] = update.message.text.strip()
    return await _save_systemic(update, context)


async def _save_systemic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bottlenecks = context.user_data.get("sys_bottlenecks", "")
    actions = context.user_data.get("sys_actions", "")

    status_msg = await update.message.reply_text("Saving to Notion...")

    result = await save_systemic_entry(bottlenecks=bottlenecks, actionable_items=actions)

    msg = result["message"] if result["success"] else f"Error: {result['message']}"
    await status_msg.edit_text(msg, reply_markup=build_main_menu())
    return ConversationHandler.END
