# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/base.py

import logging
from datetime import datetime, timedelta, timezone, date
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from bot.keyboards import (
    build_main_menu,
    build_financial_submenu,
    build_diet_submenu,
    build_journal_submenu,
)
from bot.formatting import bold, code, fmt_dur, fmt_time_with_date

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=5, minutes=30))


async def _build_main_dashboard(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Builds the main dashboard text with a quick activity summary."""
    from services.dashboard import get_dashboard_data

    now = datetime.now(TZ)
    data = await get_dashboard_data()

    if not data["ok"]:
        return "\n".join([bold("LifeOS Dashboard"), "", "<i>Could not load activity data</i>"])

    entries = data["entries"]
    total_hrs = data["total_hrs"]
    tracked_pct = data["tracked_pct"]
    untracked_hrs = data["untracked_hrs"]
    last_entry = data["last_entry"]
    untracked_since_hrs = data["untracked_since_hrs"]
    top_categories = data["top_categories"]

    lines = [
        bold("LifeOS Dashboard"),
        "",
        f"<b>Last 48h:</b> {len(entries)} entries | {code(fmt_dur(total_hrs))} tracked | {code(fmt_dur(untracked_hrs))} untracked ({tracked_pct:.0f}%)",
    ]

    # Last entry
    if last_entry:
        s = last_entry.get("start")
        e = last_entry.get("end")
        atype = last_entry.get("activity_type", "")
        title_full = last_entry.get("title", "") or atype
        time_str = ""
        if s:
            time_str = fmt_time_with_date(s, now)
        if e:
            time_str += f"-{fmt_time_with_date(e, now)}"
        lines.append(f"\n<b>Last entry:</b> {time_str} {title_full}")

        # Time since last entry ended
        if untracked_since_hrs is not None and untracked_since_hrs >= 1 and e:
            lines.append(f"<b>Untracked since:</b> {fmt_time_with_date(e, now)} ({fmt_dur(untracked_since_hrs)} ago)")

    # Category breakdown (top 3)
    if top_categories:
        cat_str = " | ".join(f"{cat} {fmt_dur(hrs)}" for cat, hrs in top_categories)
        lines.append(f"\n<b>Top:</b> {cat_str}")

    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends the main hub with quick activity summary."""
    # Store chat_id for gap alerts
    if update.effective_chat:
        context.bot_data["user_chat_id"] = update.effective_chat.id

    text = await _build_main_dashboard(context)
    keyboard = build_main_menu()

    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    return ConversationHandler.END


async def show_financial_submenu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Financial Log", reply_markup=build_financial_submenu())
    return ConversationHandler.END


async def show_diet_submenu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Diet Log", reply_markup=build_diet_submenu())
    return ConversationHandler.END


async def show_journal_submenu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Journals", reply_markup=build_journal_submenu())
    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gracefully exits any conversation and returns to main menu."""
    text = await _build_main_dashboard(context)
    keyboard = build_main_menu()
    if update.callback_query:
        query = update.callback_query
        await query.answer(text="Cancelled")
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return ConversationHandler.END
