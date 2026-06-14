# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/main.py

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)
from config import settings, reload_settings
from notion.discovery import ensure_database_ids
from bot.handlers.base import (
    start_command,
    show_financial_submenu,
    show_diet_submenu,
    show_journal_submenu,
    cancel_handler,
)

# ── Activity handler (new flow) ──
from bot.handlers.activity import (
    show_activity_dashboard,
    back_to_activity,
    undo_action,
    start_activity_flow,
    fast_add_from_gap,
    add_adjacent_before,
    add_adjacent_after,
    type_chosen as act_type_chosen,
    desc_entered as act_desc_entered,
    desc_skipped as act_desc_skipped,
    # Start time flow
    start_suggestion_chosen as act_start_sug,
    start_only_suggestion_chosen as act_start_sog,
    start_hour_chosen as act_start_hr,
    start_minute_chosen as act_start_min,
    start_minute_back as act_start_min_back,
    # End time flow
    end_suggestion_chosen as act_end_sug,
    end_hour_chosen as act_end_hr,
    end_minute_chosen as act_end_min,
    end_minute_back as act_end_min_back,
    # View & CRUD
    daily_view_callback,
    show_entry_detail,
    # Edit flows
    edit_type_start,
    edit_type_chosen,
    edit_desc_start,
    edit_desc_entered,
    edit_time_start,
    edit_start_hour_chosen,
    edit_start_minute_chosen,
    edit_start_minute_back,
    edit_end_hour_chosen,
    edit_end_minute_chosen,
    edit_end_minute_back,
    edit_offset_chosen,
    edit_start_custom,
    edit_end_custom,
    delete_entry_confirm,
    show_gaps_callback,
    check_activity_gaps,
    gapreport_command,
    # States
    CHOOSE_TYPE as ACT_TYPE,
    ENTER_DESC as ACT_DESC,
    CHOOSE_START as ACT_START,
    CHOOSE_END as ACT_END,
    EDT_CHOOSE_TYPE,
    EDT_ENTER_DESC,
    EDT_CHOOSE_START,
    EDT_CHOOSE_END,
    EDT_SHOW_OFFSETS,
)

# ── Financial handler ──
from bot.handlers.financial import (
    start_financial_flow,
    type_chosen as fin_type_chosen,
    amount_entered as fin_amount_entered,
    category_chosen as fin_category_chosen,
    skip_note as fin_skip_note,
    note_entered as fin_note_entered,
    CHOOSE_TYPE as FIN_TYPE,
    ENTER_AMOUNT as FIN_AMT,
    CHOOSE_CATEGORY as FIN_CAT,
    ENTER_NOTE as FIN_NOTE,
    financial_edit_conv,
)

# ── Diet handler ──
from bot.handlers.diet import (
    start_diet_flow,
    meal_chosen as diet_meal_chosen,
    description_entered as diet_desc_entered,
    skip_calories as diet_skip_cal,
    calories_entered as diet_cal_entered,
    skip_note as diet_skip_note,
    note_entered as diet_note_entered,
    CHOOSE_MEAL as DIET_MEAL,
    ENTER_DESCRIPTION as DIET_DESC,
    ENTER_CALORIES as DIET_CAL,
    ENTER_NOTE as DIET_NOTE,
    diet_edit_conv,
)

# ── Journal handlers ──
from bot.handlers.journal import (
    start_subjective_flow,
    subjective_energy,
    subjective_focus,
    subjective_happiness,
    subjective_skip_gratitude,
    subjective_gratitude,
    SUBJ_ENERGY,
    SUBJ_FOCUS,
    SUBJ_HAPPINESS,
    SUBJ_GRATITUDE,
    start_relational_flow,
    relational_person,
    relational_quality,
    relational_skip_insights,
    relational_insights,
    REL_PERSON,
    REL_QUALITY,
    REL_INSIGHTS,
    start_systemic_flow,
    systemic_bottlenecks,
    systemic_actions,
    SYS_BOTTLENECKS,
    SYS_ACTIONS,
)

# ── Logging ──
LOG_FORMAT = "%(asctime)s %(name)-25s %(levelname)-7s %(message)s"
LOG_DATE = "%Y-%m-%d %H:%M:%S"

_running_under_systemd = os.environ.get("INVOCATION_ID") is not None

if _running_under_systemd:
    logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_DATE, level=logging.INFO)
else:
    import pathlib
    LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    pathlib.Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "bot.log")
    logging.basicConfig(
        format=LOG_FORMAT, datefmt=LOG_DATE, level=logging.INFO,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

logger = logging.getLogger(__name__)


# ── Conversation Builders ────────────────────────────────────────────────────

def build_activity_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_activity_flow, pattern="^menu:activity$"),
            CallbackQueryHandler(fast_add_from_gap, pattern="^act_gap:"),
            CallbackQueryHandler(add_adjacent_before, pattern="^adj_before:"),
            CallbackQueryHandler(add_adjacent_after, pattern="^adj_after:"),
        ],
        states={
            ACT_START: [
                CallbackQueryHandler(act_start_sug, pattern="^s_sug:"),
                CallbackQueryHandler(act_start_sog, pattern="^s_sog:"),
                CallbackQueryHandler(act_start_hr, pattern="^s_hr:"),
                CallbackQueryHandler(act_start_min, pattern="^s_min:"),
                CallbackQueryHandler(act_start_min_back, pattern="^s_min_back$"),
            ],
            ACT_END: [
                CallbackQueryHandler(act_end_sug, pattern="^e_sug:"),
                CallbackQueryHandler(act_end_hr, pattern="^e_hr:"),
                CallbackQueryHandler(act_end_min, pattern="^e_min:"),
                CallbackQueryHandler(act_end_min_back, pattern="^e_min_back$"),
            ],
            ACT_TYPE: [CallbackQueryHandler(act_type_chosen, pattern="^act_type:")],
            ACT_DESC: [
                CallbackQueryHandler(act_desc_skipped, pattern="^act_desc:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, act_desc_entered),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$"),
            CallbackQueryHandler(back_to_activity, pattern="^act_back_dash$"),
        ],
        per_message=False,
        allow_reentry=True,
    )


def build_edit_type_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_type_start, pattern="^edt_type:")],
        states={
            EDT_CHOOSE_TYPE: [CallbackQueryHandler(edit_type_chosen, pattern="^edt_type_val:")],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


def build_edit_desc_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_desc_start, pattern="^edt_desc:")],
        states={
            EDT_ENTER_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_desc_entered)],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


def build_edit_time_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_time_start, pattern="^edt_time:")],
        states={
            EDT_SHOW_OFFSETS: [
                CallbackQueryHandler(edit_offset_chosen, pattern="^edt_offset:"),
                CallbackQueryHandler(edit_start_custom, pattern="^edt_start_custom$"),
                CallbackQueryHandler(edit_end_custom, pattern="^edt_end_custom$"),
            ],
            EDT_CHOOSE_START: [
                CallbackQueryHandler(edit_start_hour_chosen, pattern="^edt_sh:"),
                CallbackQueryHandler(edit_start_minute_chosen, pattern="^edt_sm:"),
                CallbackQueryHandler(edit_start_minute_back, pattern="^edt_sm_back$"),
            ],
            EDT_CHOOSE_END: [
                CallbackQueryHandler(edit_end_hour_chosen, pattern="^edt_eh:"),
                CallbackQueryHandler(edit_end_minute_chosen, pattern="^edt_em:"),
                CallbackQueryHandler(edit_end_minute_back, pattern="^edt_em_back$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


def build_financial_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_financial_flow, pattern="^menu:financial$")],
        states={
            FIN_TYPE: [CallbackQueryHandler(fin_type_chosen, pattern="^fin_type:")],
            FIN_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_amount_entered)],
            FIN_CAT: [CallbackQueryHandler(fin_category_chosen, pattern="^fin_cat:")],
            FIN_NOTE: [
                CallbackQueryHandler(fin_skip_note, pattern="^fin_note:Skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fin_note_entered),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


def build_diet_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_diet_flow, pattern="^menu:diet$")],
        states={
            DIET_MEAL: [CallbackQueryHandler(diet_meal_chosen, pattern="^diet_meal:")],
            DIET_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, diet_desc_entered)],
            DIET_CAL: [
                CallbackQueryHandler(diet_skip_cal, pattern="^diet_cal:Skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, diet_cal_entered),
            ],
            DIET_NOTE: [
                CallbackQueryHandler(diet_skip_note, pattern="^diet_note:Skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, diet_note_entered),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


def build_subjective_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_subjective_flow, pattern="^menu:subjective_journal$")],
        states={
            SUBJ_ENERGY: [CallbackQueryHandler(subjective_energy, pattern="^subj_energy:")],
            SUBJ_FOCUS: [CallbackQueryHandler(subjective_focus, pattern="^subj_focus:")],
            SUBJ_HAPPINESS: [CallbackQueryHandler(subjective_happiness, pattern="^subj_happiness:")],
            SUBJ_GRATITUDE: [
                CallbackQueryHandler(subjective_skip_gratitude, pattern="^subj_grat:Skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, subjective_gratitude),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


def build_relational_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_relational_flow, pattern="^menu:relational_journal$")],
        states={
            REL_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, relational_person)],
            REL_QUALITY: [CallbackQueryHandler(relational_quality, pattern="^rel_quality:")],
            REL_INSIGHTS: [
                CallbackQueryHandler(relational_skip_insights, pattern="^rel_insights:Skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, relational_insights),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


def build_systemic_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_systemic_flow, pattern="^menu:systemic_journal$")],
        states={
            SYS_BOTTLENECKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, systemic_bottlenecks)],
            SYS_ACTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, systemic_actions)],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel_flow$")],
        per_message=False,
        allow_reentry=True,
    )


# ── Discovery ────────────────────────────────────────────────────────────────

async def _run_discovery() -> None:
    ids = await ensure_database_ids(settings.NOTION_API_KEY)
    if ids:
        reload_settings()
        logger.info("Config reloaded with discovered database IDs.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing!")
        return
    if not settings.NOTION_API_KEY:
        logger.error("NOTION_API_KEY is missing!")
        return

    logger.info("Running Notion database discovery...")
    asyncio.run(_run_discovery())

    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Store chat_id on every message (not callbacks)
    async def store_chat_id(update: Update, context):
        if update.message and update.effective_chat:
            context.bot_data["user_chat_id"] = update.effective_chat.id

    application.add_handler(MessageHandler(filters.ALL, store_chat_id), group=-1)

    # Error handler
    async def error_handler(update: object, context) -> None:
        logger.error(f"Exception while handling update: {context.error}", exc_info=context.error)
        if update and hasattr(update, "callback_query") and update.callback_query:
            try:
                await update.callback_query.answer("An error occurred. Please try again.")
            except Exception:
                pass

    application.add_error_handler(error_handler)

    # /start command
    application.add_handler(CommandHandler("start", start_command))

    # Sub-menu navigation
    application.add_handler(CallbackQueryHandler(show_activity_dashboard, pattern="^sub:activity$"))
    application.add_handler(CallbackQueryHandler(show_financial_submenu, pattern="^sub:financial$"))
    application.add_handler(CallbackQueryHandler(show_diet_submenu, pattern="^sub:diet$"))
    application.add_handler(CallbackQueryHandler(show_journal_submenu, pattern="^sub:journal$"))
    application.add_handler(CallbackQueryHandler(start_command, pattern="^menu:main$"))

    # No-op handler for decorative separator buttons
    async def noop_handler(update: Update, context):
        await update.callback_query.answer()

    application.add_handler(CallbackQueryHandler(noop_handler, pattern="^noop$"))

    # Activity view + entry detail + delete (non-conversation callbacks)
    application.add_handler(CallbackQueryHandler(daily_view_callback, pattern="^act_view:"))
    application.add_handler(CallbackQueryHandler(show_entry_detail, pattern="^act_entry:"))
    application.add_handler(CallbackQueryHandler(delete_entry_confirm, pattern="^edt_del:"))
    application.add_handler(CallbackQueryHandler(show_gaps_callback, pattern="^act_gaps:"))
    application.add_handler(CallbackQueryHandler(back_to_activity, pattern="^act_back_dash$"))
    application.add_handler(CallbackQueryHandler(undo_action, pattern="^undo_action$"))
    application.add_handler(CommandHandler("gapreport", gapreport_command))

    # Conversation handlers
    application.add_handler(build_activity_conversation())
    application.add_handler(build_edit_type_conversation())
    application.add_handler(build_edit_desc_conversation())
    application.add_handler(build_edit_time_conversation())
    application.add_handler(build_financial_conversation())
    application.add_handler(build_diet_conversation())
    application.add_handler(build_subjective_conversation())
    application.add_handler(build_relational_conversation())
    application.add_handler(build_systemic_conversation())
    application.add_handler(diet_edit_conv)
    application.add_handler(financial_edit_conv)

    # Gap detection job
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_activity_gaps, interval=900, first=60)
        logger.info("Gap detection job scheduled (every 15 min).")

    logger.info("LifeOS Bot starting polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
