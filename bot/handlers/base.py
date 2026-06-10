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
    from notion.client import notion_manager

    now = datetime.now(TZ)
    today = date.today()
    h48_ago = now - timedelta(hours=48)

    try:
        # Fetch last 48h of activity entries using overlap detection
        two_days_ago = (now - timedelta(hours=48)).date().isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        all_entries = await notion_manager.query_activity_entries(two_days_ago, tomorrow)
        all_entries.sort(key=lambda e: e.get("start", datetime.min))

        # Overlap: include entries whose start OR end falls within 48h window
        def overlaps(entry):
            s = entry.get("start")
            e = entry.get("end")
            if not s:
                return False
            e = e or now
            return s < now and e > h48_ago

        entries = [e for e in all_entries if overlaps(e)]

        total_hrs = sum(e.get("duration_hrs", 0) for e in entries)
        tracked_pct = (total_hrs / 48 * 100) if total_hrs else 0
        untracked_hrs = max(0, 48 - total_hrs)

        lines = [
            bold("LifeOS Dashboard"),
            "",
            f"<b>Last 48h:</b> {len(entries)} entries | {code(fmt_dur(total_hrs))} tracked | {code(fmt_dur(untracked_hrs))} untracked ({tracked_pct:.0f}%)",
        ]

        # Last entry
        if entries:
            last = entries[-1]
            s = last.get("start")
            e = last.get("end")
            atype = last.get("activity_type", "")
            title_full = last.get("title", "") or atype
            time_str = ""
            if s:
                time_str = fmt_time_with_date(s, now)
            if e:
                time_str += f"-{fmt_time_with_date(e, now)}"
            lines.append(f"\n<b>Last entry:</b> {time_str} {title_full}")

            # Time since last entry ended
            if e and e < now:
                gap = (now - e).total_seconds() / 3600
                if gap >= 1:
                    lines.append(f"<b>Untracked since:</b> {fmt_time_with_date(e, now)} ({fmt_dur(gap)} ago)")

        # Category breakdown (top 3)
        cat_hours = {}
        for e in entries:
            cat = e.get("activity_type", "Other") or "Other"
            cat_hours[cat] = cat_hours.get(cat, 0) + e.get("duration_hrs", 0)
        if cat_hours:
            sorted_cats = sorted(cat_hours.items(), key=lambda x: -x[1])[:3]
            cat_str = " | ".join(f"{cat} {fmt_dur(hrs)}" for cat, hrs in sorted_cats)
            lines.append(f"\n<b>Top:</b> {cat_str}")

    except Exception as e:
        logger.error(f"Failed to build main dashboard: {e}")
        lines = [bold("LifeOS Dashboard"), "", "<i>Could not load activity data</i>"]

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
