# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/journal.py

import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from config import settings
from notion.client import notion_manager
from notion.models import NotionPayloadBuilder as NB
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

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = [f"E:{energy}" if energy else "", f"F:{focus}" if focus else "", f"H:{happiness}" if happiness else ""]
    title_str = " | ".join(p for p in parts if p) or "Journal Entry"

    properties = {
        "Name": NB.title(f"{now} — {title_str}"),
        "Date": NB.date(now),
        "Gratitude": NB.rich_text(gratitude),
    }
    if energy is not None:
        properties["Energy"] = NB.number(energy)
    if focus is not None:
        properties["Focus"] = NB.number(focus)
    if happiness is not None:
        properties["Happiness"] = NB.number(happiness)

    try:
        await notion_manager.create_page(settings.DATABASE_ID_SUBJECTIVE_JOURNAL, properties)
        success = f"Subjective journal logged: {title_str}"
    except Exception as e:
        logger.error(f"Failed to save subjective journal: {e}")
        success = f"Error: {e}"

    reply_markup = build_main_menu()
    if update.callback_query:
        await update.callback_query.edit_message_text(success, reply_markup=reply_markup)
    else:
        await status_msg.edit_text(success, reply_markup=reply_markup)
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

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    properties = {
        "Name": NB.title(f"{person} — {now}"),
        "Date": NB.date(now),
        "Insights": NB.rich_text(insights),
    }
    if quality is not None:
        properties["Connection Quality"] = NB.number(quality)

    try:
        await notion_manager.create_page(settings.DATABASE_ID_RELATIONAL_JOURNAL, properties)
        success = f"Relational journal logged: {person}"
    except Exception as e:
        logger.error(f"Failed to save relational journal: {e}")
        success = f"Error: {e}"

    reply_markup = build_main_menu()
    if update.callback_query:
        await update.callback_query.edit_message_text(success, reply_markup=reply_markup)
    else:
        await status_msg.edit_text(success, reply_markup=reply_markup)
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

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    properties = {
        "Name": NB.title(f"Systemic Review — {now}"),
        "Date": NB.date(now),
        "Bottlenecks": NB.rich_text(bottlenecks),
        "Actionable Items": NB.rich_text(actions),
        "Done": NB.checkbox(False),
    }

    try:
        await notion_manager.create_page(settings.DATABASE_ID_SYSTEMIC_JOURNAL, properties)
        success = "Systemic journal logged."
    except Exception as e:
        logger.error(f"Failed to save systemic journal: {e}")
        success = f"Error: {e}"

    await status_msg.edit_text(success, reply_markup=build_main_menu())
    return ConversationHandler.END
