# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/handlers/activity.py

import logging
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import settings
from notion.client import notion_manager
from notion.models import NotionPayloadBuilder as NB
from bot.keyboards import (
    build_grid_keyboard,
    build_hour_keyboard,
    build_minute_keyboard,
    build_suggestions_keyboard,
    build_activity_dashboard_keyboard,
    build_activity_dashboard_with_entries_keyboard,
    build_rolling_view_keyboard,
    build_entry_detail_keyboard,
    build_confirm_keyboard,
    build_back_button,
)
from bot.formatting import (
    fmt_dur, fmt_time, fmt_date, fmt_pct,
    bold, escape,
    render_dashboard, render_rolling_view, render_entry_detail, render_gap_report,
    render_mini_timeline, render_timeline_with_marker,
)
from bot.insights import analyze_patterns, predict_next_activity, render_insights_section, generate_smart_suggestions

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=5, minutes=30))  # IST

# ── New Entry Conversation States (order: start → end → type → desc) ──
CHOOSE_START, CHOOSE_END, CHOOSE_TYPE, ENTER_DESC = range(4)

# ── Edit Conversation States ──
EDT_CHOOSE_TYPE, EDT_ENTER_DESC, EDT_CHOOSE_START, EDT_CHOOSE_END = range(4, 8)

# Types that auto-skip description
NO_DESC_TYPES = {"Sleep", "Meditation", "Recreation", "Gaming", "Reels", "Videos", "Nap"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def round_to_15(dt: datetime) -> datetime:
    minutes = dt.minute
    rounded = (minutes + 7) // 15 * 15
    if rounded == 60:
        dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        dt = dt.replace(minute=rounded, second=0, microsecond=0)
    return dt


def hhmm_to_dt(hhmm: str, base_date: date) -> datetime:
    """Converts HHMM string to datetime on base_date."""
    h, m = int(hhmm[:2]), int(hhmm[2:])
    return datetime(base_date.year, base_date.month, base_date.day, h, m, tzinfo=TZ)


def dt_to_hhmm(dt: datetime) -> str:
    return dt.strftime("%H%M")


# ── Activity Dashboard ───────────────────────────────────────────────────────

async def show_activity_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows the activity dashboard with stats when user taps Activity from main menu."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Loading dashboard...")

    today = date.today()
    now = datetime.now(TZ)

    # Fetch entries for 30 days (covers 48h, 7d, 30d)
    # Sort descending so recent entries are always in the first page (100 limit)
    month_ago = (today - timedelta(days=30)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    all_entries = await notion_manager.query_activity_entries(month_ago, tomorrow, sort_ascending=False)

    # Sort ascending for timeline display and correct last-entry detection
    all_entries.sort(key=lambda e: e.get("start", datetime.min))

    # Split into time ranges using OVERLAP detection
    # An entry overlaps a window if start < window_end AND end > window_start
    # This catches long entries (e.g. 8h sleep) that started before the window
    h48_start = now - timedelta(hours=48)
    d7_start = datetime.combine(today - timedelta(days=7), datetime.min.time(), tzinfo=TZ)

    def overlaps(entry, window_start, window_end):
        s = entry.get("start")
        e = entry.get("end")
        if not s:
            return False
        e = e or now  # if no end time, assume ongoing
        return s < window_end and e > window_start

    entries_48h = [e for e in all_entries if overlaps(e, h48_start, now)]
    entries_7d = [e for e in all_entries if overlaps(e, d7_start, now)]
    entries_30d = all_entries

    def stats(entries):
        count = len(entries)
        total_hrs = sum(e.get("duration_hrs", 0) for e in entries)
        return count, total_hrs

    c48, h48 = stats(entries_48h)
    c7, h7 = stats(entries_7d)
    c30, h30 = stats(entries_30d)

    # Category breakdown for 7d
    cat_hours: Dict[str, float] = {}
    for e in entries_7d:
        cat = e.get("activity_type", "Other") or "Other"
        cat_hours[cat] = cat_hours.get(cat, 0) + e.get("duration_hrs", 0)
    sorted_cats = sorted(cat_hours.items(), key=lambda x: -x[1])

    # ── Insights & Predictions ──
    patterns = analyze_patterns(all_entries)
    last_entry = all_entries[-1] if all_entries else None
    last_type = last_entry.get("activity_type") if last_entry else None
    predictions = predict_next_activity(patterns, last_type=last_type, current_time=now)

    dashboard_text = render_dashboard(c48, h48, c7, h7, c30, h30, sorted_cats)
    insights_text = render_insights_section(patterns, predictions)

    # ── Smart suggestions ──
    suggestions = generate_smart_suggestions(entries_48h, patterns, now)
    suggestions_text = ""
    if suggestions:
        suggestions_text = "\n\n<b>Smart Suggestions</b>\n" + "\n".join(f"  {s}" for s in suggestions)

    # Store entries in context for CRUD operations
    context.user_data["view_entries"] = {e["page_id"]: e for e in entries_48h}

    # Build entry labels and gap buttons
    entry_ids = []
    entry_labels = []
    gap_btns = []

    for i, e in enumerate(entries_48h):
        start = e.get("start")
        end = e.get("end")
        title_full = e.get("title", "") or e.get("activity_type", "")
        dur = e.get("duration_hrs", 0)
        page_id = e.get("page_id", "")

        time_str = ""
        if start:
            time_str = _fmt_time_with_date(start, now)
        if end:
            time_str += f"-{_fmt_time_with_date(end, now)}"

        label = f"{time_str} {title_full} ({fmt_dur(dur)})"
        if len(label) > 50:
            label = label[:47] + "..."

        entry_ids.append(page_id)
        entry_labels.append(label)

        # Gap after this entry
        if i < len(entries_48h) - 1:
            next_start = entries_48h[i + 1].get("start")
            if end and next_start:
                gap_hrs = (next_start - end).total_seconds() / 3600
                if gap_hrs >= 0.5:
                    gap_start_str = _fmt_time_with_date(end, now)
                    gap_end_str = _fmt_time_with_date(next_start, now)
                    gap_btns.append({
                        "start_hhmm": end.strftime("%Y%m%dT%H%M"),
                        "end_hhmm": next_start.strftime("%Y%m%dT%H%M"),
                        "label": f"Fill gap: {gap_start_str}-{gap_end_str} ({fmt_dur(gap_hrs)})",
                    })

    # Gap from last entry to now
    if entries_48h:
        last_end = entries_48h[-1].get("end")
        if last_end and last_end < now:
            gap_to_now = (now - last_end).total_seconds() / 3600
            if gap_to_now >= 0.5:
                gap_start_str = _fmt_time_with_date(last_end, now)
                gap_end_str = _fmt_time_with_date(now, now)
                gap_btns.append({
                    "start_hhmm": last_end.strftime("%Y%m%dT%H%M"),
                    "end_hhmm": now.strftime("%Y%m%dT%H%M"),
                    "label": f"Fill gap: {gap_start_str}-{gap_end_str} ({fmt_dur(gap_to_now)})",
                })

    # Build keyboard with entries + gaps
    if entry_ids:
        dash_keyboard = build_activity_dashboard_with_entries_keyboard(entry_ids, entry_labels, gap_btns)
    else:
        dash_keyboard = build_activity_dashboard_keyboard()

    # Timeline section — show last 48h entries
    timeline = render_mini_timeline(entries_48h, "Last 48h")

    text = f"{dashboard_text}\n\n{insights_text}{suggestions_text}\n\n{timeline}"
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await query.edit_message_text(text, reply_markup=dash_keyboard, parse_mode="HTML")
    return ConversationHandler.END


# ── Back to Activity Dashboard ────────────────────────────────────────────────

async def back_to_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Returns to activity dashboard from any entry flow step."""
    return await show_activity_dashboard(update, context)


# ── New Entry Flow ───────────────────────────────────────────────────────────

async def start_activity_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: shows start time picker (timing first, then what)."""
    query = update.callback_query
    await query.answer()

    # Clear stale time data from previous flows
    context.user_data.pop("act_start", None)
    context.user_data.pop("act_end", None)

    # Pre-fetch activity types for later
    types = await notion_manager.get_activity_types()
    context.user_data["activity_types"] = [t["name"] for t in types] if types else [
        "Work", "Workout", "Shadow Work", "Trading", "Networking",
        "Meeting", "Meditation", "Brain Games", "Sleep", "Chores",
        "Recreation", "Study", "Socialize", "Content Creation",
    ]

    return await _show_start_time_picker(update, context)


async def type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """After type selected, ask description (or skip to notes for no-desc types)."""
    query = update.callback_query
    await query.answer()
    logger.info(f"[TYPE_CHOSEN] Callback data: {query.data}")
    atype = query.data.split(":", 1)[1]
    context.user_data["act_type"] = atype

    # Fast-add: times already pre-filled, go straight to desc or save
    if context.user_data.get("fast_add"):
        context.user_data.pop("fast_add", None)
        if atype in NO_DESC_TYPES:
            context.user_data["act_desc"] = ""
            return await _save_activity(update, context)
        await query.edit_message_text(
            f"Type: <b>{escape(atype)}</b>\nEnter description:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="Skip", callback_data="act_desc:skip")],
                [InlineKeyboardButton(text="Back to Activity", callback_data="act_back_dash")],
            ]),
            parse_mode="HTML",
        )
        return ENTER_DESC

    # No-desc types skip description and go straight to notes
    if atype in NO_DESC_TYPES:
        context.user_data["act_desc"] = ""
        return await _save_activity(update, context)

    await query.edit_message_text(
        f"Type: <b>{escape(atype)}</b>\nEnter description:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(text="Skip", callback_data="act_desc:skip")],
            [InlineKeyboardButton(text="Back to Activity", callback_data="act_back_dash")],
        ]),
        parse_mode="HTML",
    )
    return ENTER_DESC


async def desc_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """After description entered, save the activity."""
    context.user_data["act_desc"] = update.message.text.strip()
    if context.user_data.get("fast_add"):
        context.user_data.pop("fast_add", None)
    return await _save_activity(update, context)


async def desc_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """After description skipped, save the activity."""
    query = update.callback_query
    await query.answer()
    context.user_data["act_desc"] = ""
    if context.user_data.get("fast_add"):
        context.user_data.pop("fast_add", None)
    return await _save_activity(update, context)


def _fmt_time_with_date(dt: datetime, reference: datetime) -> str:
    """Format time, showing date if different from reference."""
    if dt.date() == reference.date():
        return fmt_time(dt)
    return f"{dt.strftime('%b %d')} {fmt_time(dt)}"


def _compute_time_suggestions(entries_48h: List[dict], now: datetime, last_saved_end: Optional[datetime] = None) -> List[dict]:
    """
    Finds gaps in the past 48h and generates quick-fill suggestions.
    Each gap gets +15m/+30m/+45m/+1h/+1.5h/+2h end-time options from the gap start.
    Returns list of {label, start_hhmm, end_hhmm, start_only}.
    """
    suggestions = []
    now_rounded = round_to_15(now)

    # Find ALL gaps in entries
    gaps = []
    for i in range(len(entries_48h) - 1):
        end = entries_48h[i].get("end")
        next_start = entries_48h[i + 1].get("start")
        if end and next_start:
            gap_hrs = (next_start - end).total_seconds() / 3600
            if gap_hrs >= 0.25:
                gaps.append({"start": end, "end": next_start, "hours": gap_hrs})

    # Gap from last entry end to now (open-ended gap)
    last_end = None
    if last_saved_end:
        last_end = last_saved_end
    elif entries_48h:
        last_end = entries_48h[-1].get("end")

    if last_end and last_end < now_rounded:
        gap_hrs = (now_rounded - last_end).total_seconds() / 3600
        if gap_hrs >= 0.25:
            gaps.append({"start": last_end, "end": now_rounded, "hours": gap_hrs, "open": True})

    # For each gap, generate quick-fill suggestions
    for g in gaps:
        gap_start = g["start"]
        gap_end = g["end"]
        gap_hours = g["hours"]
        is_open = g.get("open", False)

        # Quick-fill end times from gap start — show as clean time ranges
        # Use compact ISO format (YYYYMMDDTHHMM) in callback to preserve correct date
        for mins in [15, 30, 45, 60, 90, 120]:
            end_dt = round_to_15(gap_start + timedelta(minutes=mins))
            if end_dt > gap_end and not is_open:
                continue
            s_str = _fmt_time_with_date(gap_start, now)
            e_str = _fmt_time_with_date(end_dt, now)
            s_compact = gap_start.strftime("%Y%m%dT%H%M")
            e_compact = end_dt.strftime("%Y%m%dT%H%M")
            suggestions.append({
                "label": f"{s_str} → {e_str} ({fmt_dur(mins / 60)})",
                "start_hhmm": s_compact,
                "end_hhmm": e_compact,
                "start_only": False,
                "gap_start": gap_start,
            })

        # Fill entire gap
        if not is_open:
            s_str = _fmt_time_with_date(gap_start, now)
            e_str = _fmt_time_with_date(gap_end, now)
            s_compact = gap_start.strftime("%Y%m%dT%H%M")
            e_compact = gap_end.strftime("%Y%m%dT%H%M")
            suggestions.append({
                "label": f"{s_str} → {e_str} ({fmt_dur(gap_hours)}) — Fill all",
                "start_hhmm": s_compact,
                "end_hhmm": e_compact,
                "start_only": False,
                "gap_start": gap_start,
            })

    # "Now" as a fallback
    suggestions.append({
        "label": f"Now: start {_fmt_time_with_date(now_rounded, now)}",
        "start_hhmm": now_rounded.strftime("%Y%m%dT%H%M"),
        "start_only": True,
    })

    return suggestions


async def _show_start_time_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows gap-based suggestions + timeline for start time."""
    now = round_to_15(datetime.now(TZ))
    context.user_data["pick_date"] = date.today().isoformat()

    title = "New Entry"

    # Fetch 48h of entries for gap detection
    h48_start = (now - timedelta(hours=48)).date()
    h48_start_dt = datetime.combine(h48_start, datetime.min.time(), tzinfo=TZ)
    tomorrow = datetime.combine(date.today() + timedelta(days=1), datetime.min.time(), tzinfo=TZ)
    entries_48h = await notion_manager.query_activity_entries(
        h48_start_dt.date().isoformat(), tomorrow.date().isoformat()
    )
    entries_48h.sort(key=lambda e: e.get("start", datetime.min))
    context.user_data["recent_entries"] = entries_48h

    # Get last saved end for continuous logging
    last_saved_end = context.user_data.get("last_saved_end")

    # Compute smart suggestions based on 48h gaps
    suggestions = _compute_time_suggestions(entries_48h, now, last_saved_end)
    timeline = render_timeline_with_marker(entries_48h, now, now + timedelta(hours=1), title)

    text = f"{timeline}\n\n<b>{escape(title)}</b>\nSelect START time:"

    # Build keyboard: gap-based suggestions + entry buttons for CRUD
    keyboard_rows = []
    for s in suggestions:
        if s.get("start_only"):
            cb = f"s_sog:{s['start_hhmm']}"
        else:
            cb = f"s_sug:{s['start_hhmm']}-{s['end_hhmm']}"
        keyboard_rows.append([InlineKeyboardButton(text=s["label"], callback_data=cb)])
    keyboard_rows.append([InlineKeyboardButton(text="Custom time...", callback_data="s_sug:custom")])

    # Custom end time: start from last entry's end, then pick end
    if entries_48h:
        last_entry = entries_48h[-1]
        last_end = last_entry.get("end")
        if last_end and last_end < now:
            last_end_compact = last_end.strftime("%Y%m%dT%H%M")
            keyboard_rows.append([InlineKeyboardButton(
                text=f"Custom end time (from {_fmt_time_with_date(last_end, now)})",
                callback_data=f"s_sog:{last_end_compact}",
            )])

    # Entry buttons for CRUD (last 5 entries)
    if entries_48h:
        keyboard_rows.append([InlineKeyboardButton(text="── Recent entries ──", callback_data="noop")])
        for e in entries_48h[-5:]:
            s = e.get("start")
            end = e.get("end")
            a = e.get("activity_type", "")
            d = e.get("duration_hrs", 0)
            pid = e.get("page_id", "")
            t = _fmt_time_with_date(s, now) if s else ""
            if end:
                t += f"-{_fmt_time_with_date(end, now)}"
            lbl = f"{t} {a} ({fmt_dur(d)})"
            if len(lbl) > 50:
                lbl = lbl[:47] + "..."
            keyboard_rows.append([InlineKeyboardButton(text=lbl, callback_data=f"act_entry:{pid[:36]}")])
    keyboard_rows.append([InlineKeyboardButton(text="Back to Activity", callback_data="act_back_dash")])

    keyboard = InlineKeyboardMarkup(keyboard_rows)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return CHOOSE_START


def _parse_compact_dt(compact: str) -> datetime:
    """Parses compact ISO datetime (YYYYMMDDTHHMM) back to datetime with TZ."""
    dt = datetime.strptime(compact, "%Y%m%dT%H%M")
    return dt.replace(tzinfo=TZ)


async def start_suggestion_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles a full suggestion (pre-fills both start and end with correct dates).
    Shows the end picker so the user can customize the end time if needed,
    rather than jumping straight to the type picker.
    """
    query = update.callback_query
    await query.answer()
    logger.info(f"[START_SUG] Callback data: {query.data}")

    raw = query.data.split(":", 1)[1]
    if raw == "custom":
        await query.edit_message_text("Select START hour:", reply_markup=build_hour_keyboard("s_hr"))
        return CHOOSE_START

    # Parse compact ISO: YYYYMMDDTHHMM-YYYYMMDDTHHMM
    parts = raw.split("-")
    if len(parts) != 2:
        return CHOOSE_START

    start_dt = _parse_compact_dt(parts[0])
    end_dt = _parse_compact_dt(parts[1])

    context.user_data["act_start"] = start_dt
    context.user_data["pick_date"] = start_dt.date().isoformat()
    # If end was pre-set (e.g. Add Before flow), keep it and go to type picker
    end_was_preset = context.user_data.get("act_end") is not None
    if not end_was_preset:
        context.user_data["act_end"] = end_dt
    # Show end picker so user can accept the pre-filled end or customize it
    # unless end is locked (Add Before sets act_end to ref_start)
    if end_was_preset:
        return await _show_type_picker(update, context)
    return await _show_end_time_picker(update, context, start_dt)


async def start_only_suggestion_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles a start-only suggestion (sets start, asks for end)."""
    query = update.callback_query
    await query.answer()

    raw = query.data.split(":", 1)[1]
    start_dt = _parse_compact_dt(raw)
    context.user_data["act_start"] = start_dt
    context.user_data["pick_date"] = start_dt.date().isoformat()

    return await _show_end_time_picker(update, context, start_dt)


async def start_hour_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles hour selection for start time, shows minute picker."""
    query = update.callback_query
    await query.answer()

    hour = int(query.data.split(":", 1)[1])
    context.user_data["s_hour"] = hour

    await query.edit_message_text(
        f"Select START minute for {hour:02d}:",
        reply_markup=build_minute_keyboard("s_min", hour),
    )
    return CHOOSE_START


async def start_minute_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles minute selection for start time, moves to end time."""
    query = update.callback_query
    await query.answer()

    hhmm = query.data.split(":", 1)[1]
    pick_date = date.fromisoformat(context.user_data.get("pick_date", date.today().isoformat()))
    start_dt = hhmm_to_dt(hhmm, pick_date)
    context.user_data["act_start"] = start_dt

    return await _show_end_time_picker(update, context, start_dt)


async def start_minute_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Goes back from minute picker to hour picker for start."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Select START hour:", reply_markup=build_hour_keyboard("s_hr"),
    )
    return CHOOSE_START


async def _show_end_time_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, start_dt: datetime) -> int:
    """Shows timeline + end time suggestions."""
    now = datetime.now(TZ)
    recent = context.user_data.get("recent_entries", [])

    atype = context.user_data.get("act_type", "")
    desc = context.user_data.get("act_desc", "")
    title = f"{atype} - {desc}" if desc else atype

    # Compute end time suggestions based on start
    suggestions = []

    # If end time was pre-filled (from gap suggestion or fast-add), show it as the first option
    prefilled_end = context.user_data.get("act_end")
    if prefilled_end and prefilled_end > start_dt:
        dur_hrs = (prefilled_end - start_dt).total_seconds() / 3600
        suggestions.append({"label": f"{fmt_dur(dur_hrs)}: {fmt_time(prefilled_end)}", "start_hhmm": start_dt.strftime("%H%M"), "end_hhmm": prefilled_end.strftime("%H%M")})

    default_end = round_to_15(start_dt + timedelta(hours=1))
    suggestions.append({"label": f"+1h: {fmt_time(default_end)}", "start_hhmm": start_dt.strftime("%H%M"), "end_hhmm": default_end.strftime("%H%M")})
    end_2h = round_to_15(start_dt + timedelta(hours=2))
    suggestions.append({"label": f"+2h: {fmt_time(end_2h)}", "start_hhmm": start_dt.strftime("%H%M"), "end_hhmm": end_2h.strftime("%H%M")})
    end_30m = round_to_15(start_dt + timedelta(minutes=30))
    suggestions.append({"label": f"+30m: {fmt_time(end_30m)}", "start_hhmm": start_dt.strftime("%H%M"), "end_hhmm": end_30m.strftime("%H%M")})

    # If there's a gap after start, suggest filling it
    for e in recent:
        e_start = e.get("start")
        if e_start and e_start > start_dt:
            gap_hrs = (e_start - start_dt).total_seconds() / 3600
            if gap_hrs >= 0.25:
                suggestions.append({"label": f"Until next: {fmt_time(e_start)} ({fmt_dur(gap_hrs)})", "start_hhmm": start_dt.strftime("%H%M"), "end_hhmm": e_start.strftime("%H%M")})
            break

    # Show timeline with marker at start time
    timeline = render_timeline_with_marker(recent, start_dt, default_end, title)

    text = f"{timeline}\n\nStart: <code>{fmt_time(start_dt)}</code>\nSelect END time:"

    # Build keyboard: suggestions + entry buttons
    keyboard_rows = []
    for s in suggestions:
        keyboard_rows.append([InlineKeyboardButton(text=s["label"], callback_data=f"e_sug:{s['start_hhmm']}-{s['end_hhmm']}")])
    keyboard_rows.append([InlineKeyboardButton(text="Custom time...", callback_data="e_sug:custom")])

    # Entry buttons for CRUD
    for entry in recent[-3:]:
        s = entry.get("start")
        e_end = entry.get("end")
        a = entry.get("activity_type", "")
        d = entry.get("duration_hrs", 0)
        pid = entry.get("page_id", "")
        t = fmt_time(s) if s else ""
        if e_end:
            t += f"-{fmt_time(e_end)}"
        lbl = f"{t} {a} ({fmt_dur(d)})"
        if len(lbl) > 50:
            lbl = lbl[:47] + "..."
        keyboard_rows.append([InlineKeyboardButton(text=lbl, callback_data=f"act_entry:{pid[:36]}")])

    keyboard_rows.append([InlineKeyboardButton(text="Back to Activity", callback_data="act_back_dash")])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
    return CHOOSE_END


async def _show_type_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows activity type selection after timing is set."""
    start_dt = context.user_data.get("act_start", round_to_15(datetime.now(TZ)))
    end_dt = context.user_data.get("act_end", start_dt + timedelta(hours=1))
    dur_hrs = (end_dt - start_dt).total_seconds() / 3600

    type_names = context.user_data.get("activity_types", [
        "Work", "Workout", "Shadow Work", "Trading", "Networking",
        "Meeting", "Meditation", "Brain Games", "Sleep", "Chores",
        "Recreation", "Study", "Socialize", "Content Creation",
    ])

    keyboard_rows = []
    row = []
    for opt in type_names:
        row.append(InlineKeyboardButton(text=opt, callback_data=f"act_type:{opt}"))
        if len(row) == 2:
            keyboard_rows.append(row)
            row = []
    if row:
        keyboard_rows.append(row)
    keyboard_rows.append([InlineKeyboardButton(text="Back to Activity", callback_data="act_back_dash")])

    text = (
        f"<code>{fmt_time(start_dt)} - {fmt_time(end_dt)}</code> ({fmt_dur(dur_hrs)})\n\n"
        f"Select activity type:"
    )

    query = update.callback_query
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
    return CHOOSE_TYPE


async def end_suggestion_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles a smart suggestion for end time, then shows type picker."""
    query = update.callback_query
    await query.answer()

    raw = query.data.split(":", 1)[1]
    if raw == "custom":
        await query.edit_message_text("Select END hour:", reply_markup=build_hour_keyboard("e_hr"))
        return CHOOSE_END

    parts = raw.split("-")
    if len(parts) != 2:
        return CHOOSE_END

    # Handle both compact ISO (YYYYMMDDTHHMM) from adjacent flows
    # and short (HHMM) format from main entry flow
    if len(parts[1]) > 4:
        # Compact ISO format — full datetime embedded in callback
        end_dt = _parse_compact_dt(parts[1])
    else:
        # Short HHMM format — resolve against pick_date
        pick_date = date.fromisoformat(context.user_data.get("pick_date", date.today().isoformat()))
        start_dt = context.user_data.get("act_start", round_to_15(datetime.now(TZ)))
        end_dt = hhmm_to_dt(parts[1], pick_date)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

    context.user_data["act_end"] = end_dt
    return await _show_type_picker(update, context)


async def end_hour_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles hour selection for end time, shows minute picker."""
    query = update.callback_query
    await query.answer()

    hour = int(query.data.split(":", 1)[1])
    context.user_data["e_hour"] = hour

    await query.edit_message_text(
        f"Select END minute for {hour:02d}:",
        reply_markup=build_minute_keyboard("e_min", hour),
    )
    return CHOOSE_END


async def end_minute_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles minute selection for end time, shows type picker."""
    query = update.callback_query
    await query.answer()

    hhmm = query.data.split(":", 1)[1]
    pick_date = date.fromisoformat(context.user_data.get("pick_date", date.today().isoformat()))
    start_dt = context.user_data.get("act_start", round_to_15(datetime.now(TZ)))
    end_dt = hhmm_to_dt(hhmm, pick_date)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    context.user_data["act_end"] = end_dt
    return await _show_type_picker(update, context)


async def end_minute_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Goes back from minute picker to hour picker for end."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Select END hour:", reply_markup=build_hour_keyboard("e_hr"),
    )
    return CHOOSE_END


async def _save_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    atype = context.user_data.get("act_type", "Other")
    desc = context.user_data.get("act_desc", "")
    start_dt = context.user_data.get("act_start", round_to_15(datetime.now(TZ)))
    end_dt = context.user_data.get("act_end", start_dt + timedelta(hours=1))
    title = f"{atype} - {desc}" if desc else atype
    status_msg = None

    logger.info(f"Saving activity: title={title}, start={start_dt}, end={end_dt}")

    if update.callback_query:
        await update.callback_query.edit_message_text("Saving...")
    else:
        status_msg = await update.message.reply_text("Saving...")

    properties = {
        "Name": NB.title(title),
        "Date": NB.date(start_dt.isoformat(), end_iso=end_dt.isoformat()),
    }

    try:
        result = await notion_manager.create_page(settings.DATABASE_ID_ACTIVITY_LOG, properties)
        new_page_id = result.get("id", "")
        dur_hrs = (end_dt - start_dt).total_seconds() / 3600
        logger.info(f"Activity saved successfully: {title} (page_id={new_page_id})")

        # Store last saved end for continuous logging
        context.user_data["last_saved_end"] = end_dt

        # Re-render rolling view centered on the entry's date (not "now")
        # This ensures the entry appears even if it's for a previous day
        now = datetime.now(TZ)
        entry_date = start_dt.date()
        window_start = datetime.combine(entry_date - timedelta(days=1), datetime.min.time(), tzinfo=TZ)
        window_end = datetime.combine(entry_date + timedelta(days=2), datetime.min.time(), tzinfo=TZ)
        start_str = window_start.date().isoformat()
        end_str = window_end.date().isoformat()
        fresh_entries = await notion_manager.query_activity_entries(start_str, end_str, sort_ascending=False)
        fresh_entries = [e for e in fresh_entries if e.get("start") and e["start"] >= window_start and e["start"] < window_end]
        fresh_entries.sort(key=lambda e: e.get("start", datetime.min))

        # Find the saved entry by page_id
        saved_idx = None
        for i, e in enumerate(fresh_entries):
            if new_page_id and e.get("page_id") == new_page_id:
                saved_idx = i
                break
        if saved_idx is None:
            logger.warning(f"Could not find saved entry (page_id={new_page_id}, start={start_dt}) among {len(fresh_entries)} entries")

        context.user_data["view_entries"] = {e["page_id"]: e for e in fresh_entries}

        if saved_idx is not None:
            show_start = max(0, saved_idx - 10)
            show_end = min(len(fresh_entries), saved_idx + 11)
            display_entries = fresh_entries[show_start:show_end]
        else:
            display_entries = fresh_entries[-21:]  # Last 21 entries as fallback

        # Build the view with entries around the saved entry
        view_text = render_rolling_view(display_entries, window_start, window_end, [])
        if len(view_text) > 3500:
            view_text = view_text[:3500] + "\n..."

        # Success banner with date context
        s_date_str = _fmt_time_with_date(start_dt, now)
        e_date_str = _fmt_time_with_date(end_dt, now)
        banner = f"{bold('Logged:')} {escape(title)} — {s_date_str}-{e_date_str} ({fmt_dur(dur_hrs)})"

        # Build keyboard: entry buttons around saved entry + continue button
        keyboard_rows = []
        for entry in display_entries[-5:]:
            s = entry.get("start")
            e = entry.get("end")
            a = entry.get("activity_type", "")
            title = entry.get("title", "")
            d = entry.get("duration_hrs", 0)
            pid = entry.get("page_id", "")
            t = ""
            if s:
                t = fmt_time(s)
            if e:
                t += f"-{fmt_time(e)}"
            lbl = f"{t} {title} ({fmt_dur(d)})"
            if len(lbl) > 50:
                lbl = lbl[:47] + "..."
            keyboard_rows.append([InlineKeyboardButton(text=lbl, callback_data=f"act_entry:{pid[:36]}")])

        keyboard_rows.append([
            InlineKeyboardButton(text="+ Add Another", callback_data="menu:activity"),
            InlineKeyboardButton(text="Done", callback_data="sub:activity"),
        ])

        text = f"{banner}\n\n{view_text}"
        keyboard = InlineKeyboardMarkup(keyboard_rows)

    except Exception as e:
        logger.error(f"Failed to save activity: {e}", exc_info=True)
        text = f"Error saving entry: {escape(str(e))}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="Try Again", callback_data="menu:activity")],
            [InlineKeyboardButton(text="Back to Activity", callback_data="sub:activity")],
        ])

    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        elif status_msg:
            await status_msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to edit success message: {e}")
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return ConversationHandler.END


# ── Daily View ────────────────────────────────────────────────────────────────

async def daily_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    date_str = query.data.split(":", 1)[1]
    if date_str == "today":
        # Rolling 24h: now - 24h to now
        now = datetime.now(TZ)
        window_end = now
        window_start = now - timedelta(hours=24)
    elif date_str == "yesterday":
        now = datetime.now(TZ)
        window_end = now - timedelta(hours=24)
        window_start = now - timedelta(hours=48)
    else:
        # Parse ISO datetime string — may be "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS+HH:MM"
        try:
            dt = datetime.fromisoformat(date_str)
            # If it's a timezone-aware datetime, extract the date and localize to IST
            window_start = datetime.combine(dt.date(), dt.time().replace(tzinfo=None), tzinfo=TZ)
            window_end = window_start + timedelta(hours=24)
        except ValueError:
            # Fallback: treat as a plain date
            target = date.fromisoformat(date_str)
            window_start = datetime.combine(target, datetime.min.time(), tzinfo=TZ)
            window_end = window_start + timedelta(hours=24)
    await _render_daily_view(update, context, window_start, window_end)


async def _render_daily_view(update: Update, context: ContextTypes.DEFAULT_TYPE, window_start: datetime, window_end: datetime) -> None:
    start_str = window_start.date().isoformat()
    end_str = (window_end.date() + timedelta(days=1)).isoformat()
    entries = await notion_manager.query_activity_entries(start_str, end_str)

    # Filter to window
    entries = [e for e in entries if e.get("start") and e["start"] >= window_start and e["start"] < window_end]
    entries.sort(key=lambda e: e.get("start", datetime.min))

    # Navigation offsets
    back_24h = (window_start - timedelta(hours=24)).isoformat()
    fwd_24h = (window_start + timedelta(hours=24)).isoformat()
    w_back = (window_start - timedelta(days=7)).isoformat()
    w_fwd = (window_start + timedelta(days=7)).isoformat()
    m_back = (window_start - timedelta(days=30)).isoformat()
    m_fwd = (window_start + timedelta(days=30)).isoformat()

    # Store entries in context for edit flow
    context.user_data["view_entries"] = {e["page_id"]: e for e in entries}
    context.user_data["view_date"] = window_start.date().isoformat()

    nav_keyboard = build_rolling_view_keyboard(back_24h, fwd_24h, w_back, w_fwd, m_back, m_fwd)

    if not entries:
        text = f"{bold(fmt_time(window_start) + ' → ' + fmt_time(window_end))}\n\nNo entries."
        await update.callback_query.edit_message_text(text, reply_markup=nav_keyboard, parse_mode="HTML")
        return

    # Compute gaps and build gap buttons
    gaps_for_render = []
    gap_buttons: List[List[InlineKeyboardButton]] = []
    for i in range(len(entries) - 1):
        end = entries[i].get("end")
        next_start = entries[i + 1].get("start")
        if end and next_start:
            gap_hrs = (next_start - end).total_seconds() / 3600
            if gap_hrs >= 0.5:
                gap_start_str = fmt_time(end)
                gap_end_str = fmt_time(next_start)
                gaps_for_render.append({
                    "after_entry_id": entries[i].get("page_id"),
                    "start": gap_start_str,
                    "end": gap_end_str,
                    "hours": gap_hrs,
                })
                gap_cb_start = end.strftime("%Y%m%dT%H%M")
                gap_cb_end = next_start.strftime("%Y%m%dT%H%M")
                gap_buttons.append([InlineKeyboardButton(
                    text=f"Fill gap: {gap_start_str}-{gap_end_str} ({fmt_dur(gap_hrs)})",
                    callback_data=f"act_gap:{gap_cb_start}-{gap_cb_end}",
                )])

    # Gap from last entry to window end
    if entries:
        last_entry = entries[-1]
        last_end = last_entry.get("end")
        if last_end and last_end < window_end:
            gap_to_end = (window_end - last_end).total_seconds() / 3600
            if gap_to_end >= 0.5:
                gap_start_str = fmt_time(last_end)
                gap_end_str = fmt_time(window_end)
                gaps_for_render.append({
                    "after_entry_id": last_entry.get("page_id"),
                    "start": gap_start_str,
                    "end": gap_end_str,
                    "hours": gap_to_end,
                })
                gap_buttons.append([InlineKeyboardButton(
                    text=f"Fill to end: {gap_start_str}-{gap_end_str} ({fmt_dur(gap_to_end)})",
                    callback_data=f"act_gap:{last_end.strftime('%Y%m%dT%H%M')}-{window_end.strftime('%Y%m%dT%H%M')}",
                )])

    # Build entry buttons
    entry_buttons: List[List[InlineKeyboardButton]] = []
    for entry in entries:
        start = entry.get("start")
        end = entry.get("end")
        title_full = entry.get("title", "") or entry.get("activity_type", "")
        dur = entry.get("duration_hrs", 0)
        page_id = entry.get("page_id", "")

        time_str = ""
        if start:
            time_str = fmt_time(start)
        if end:
            time_str += f"-{fmt_time(end)}"

        btn_label = f"{time_str} {title_full} ({fmt_dur(dur)})"
        if len(btn_label) > 50:
            btn_label = btn_label[:47] + "..."
        entry_buttons.append([InlineKeyboardButton(
            text=btn_label,
            callback_data=f"act_entry:{page_id[:36]}"
        )])

    text = render_rolling_view(entries, window_start, window_end, gaps_for_render)
    if len(text) > 4000:
        text = text[:4000] + "\n... (truncated)"

    # Build final keyboard: gap buttons + entry buttons + navigation
    keyboard_rows = []
    if gap_buttons:
        keyboard_rows.extend(gap_buttons)
    keyboard_rows.extend(entry_buttons)
    for row in nav_keyboard.inline_keyboard:
        keyboard_rows.append(row)

    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML"
    )


# ── Entry Detail / Edit ──────────────────────────────────────────────────────

async def show_entry_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows entry detail with edit/delete options."""
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]

    # Look up entry from stored view_entries (populated by daily view or dashboard)
    entries = context.user_data.get("view_entries", {})
    entry = entries.get(page_id)

    # Fallback: fetch from Notion if not in cache
    if not entry:
        logger.info(f"Entry {page_id} not in view_entries cache, fetching from Notion...")
        try:
            now = datetime.now(TZ)
            month_ago = (now - timedelta(days=30)).isoformat()
            tomorrow = (now + timedelta(days=1)).isoformat()
            all_entries = await notion_manager.query_activity_entries(month_ago, tomorrow, sort_ascending=False)
            for e in all_entries:
                if e.get("page_id") == page_id:
                    entry = e
                    break
        except Exception as e:
            logger.error(f"Failed to fetch entry from Notion: {e}")

    if not entry:
        await query.edit_message_text("Entry not found.", reply_markup=build_back_button("act_view:today"))
        return ConversationHandler.END

    # Store for editing
    context.user_data["edit_page_id"] = page_id
    context.user_data["edit_entry"] = entry

    text = render_entry_detail(entry)
    await query.edit_message_text(text, reply_markup=build_entry_detail_keyboard(page_id), parse_mode="HTML")
    return ConversationHandler.END


# ── Undo Support ─────────────────────────────────────────────────────────────

def _with_undo_button(keyboard, undo_label="Undo"):
    """Prepends an undo button to an existing keyboard."""
    undo_row = [InlineKeyboardButton(text=undo_label, callback_data="undo_action")]
    new_rows = [undo_row] + list(keyboard.inline_keyboard)
    return InlineKeyboardMarkup(new_rows)

async def undo_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generic undo handler. Restores old state and re-renders."""
    query = update.callback_query
    await query.answer("Reverting...")

    undo_state = context.user_data.pop("undo_state", None)
    if not undo_state:
        await query.edit_message_text("Nothing to undo.", reply_markup=build_back_button("sub:activity"))
        return

    action = undo_state.get("action")
    page_id = undo_state.get("page_id")

    try:
        if action == "delete":
            await notion_manager.client.pages.update(page_id=page_id, archived=False)
            # Re-render rolling view with restored entry
            now = datetime.now(TZ)
            window_start = now - timedelta(hours=24)
            window_end = now
            start_str = window_start.date().isoformat()
            end_str = (window_end.date() + timedelta(days=1)).isoformat()
            fresh = await notion_manager.query_activity_entries(start_str, end_str, sort_ascending=False)
            fresh = [e for e in fresh if e.get("start") and e["start"] >= window_start and e["start"] < window_end]
            fresh.sort(key=lambda e: e.get("start", datetime.min))
            context.user_data["view_entries"] = {e["page_id"]: e for e in fresh}
            text = render_rolling_view(fresh, window_start, window_end, [])
            if len(text) > 4000:
                text = text[:4000] + "\n..."
            keyboard_rows = [
                [InlineKeyboardButton(text="+ New Entry", callback_data="menu:activity")],
                [InlineKeyboardButton(text="Back", callback_data="sub:activity")],
            ]
            await query.edit_message_text(f"{text}\n\n{bold('Undo: deletion restored')}", reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")

        elif action in ("edit_type", "edit_desc", "edit_times"):
            old_props = undo_state.get("old_properties", {})
            if old_props:
                await notion_manager.update_page(page_id, old_props)
                # Re-render entry detail with restored state
                # Re-fetch the entry
                entry = context.user_data.get("edit_entry", {})
                if action == "edit_type" and "Name" in old_props:
                    old_title = old_props["Name"].get("title", [{}])[0].get("text", {}).get("content", "")
                    entry["title"] = old_title
                elif action == "edit_times" and "Date" in old_props:
                    # Can't easily parse back, just re-fetch
                    pass
                context.user_data["edit_entry"] = entry
                text = render_entry_detail(entry)
                keyboard = build_entry_detail_keyboard(page_id)
                keyboard = _with_undo_button(keyboard, "Undo reverted")
                await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await query.edit_message_text("Nothing to undo.", reply_markup=build_back_button("sub:activity"))
        else:
            await query.edit_message_text("Unknown undo action.", reply_markup=build_back_button("sub:activity"))
    except Exception as e:
        logger.error(f"Undo failed: {e}", exc_info=True)
        await query.edit_message_text(f"Undo failed: {escape(str(e))}", reply_markup=build_back_button("sub:activity"))


# ── Edit Type Flow (direct execution) ────────────────────────────────────────

async def edit_type_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    page_id = query.data.split(":", 1)[1]
    context.user_data["edit_page_id"] = page_id

    types = await notion_manager.get_activity_types()
    type_names = [t["name"] for t in types] if types else [
        "Work", "Workout", "Shadow Work", "Trading", "Networking",
        "Meeting", "Meditation", "Brain Games", "Sleep", "Chores",
        "Recreation", "Study", "Socialize", "Content Creation",
    ]
    keyboard = build_grid_keyboard(type_names, "edt_type_val", row_width=2)
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="Back to Entry", callback_data=f"act_entry:{page_id[:36]}"),
    ])
    await query.edit_message_text("Select new activity type:", reply_markup=keyboard)
    return EDT_CHOOSE_TYPE


async def edit_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    new_type = query.data.split(":", 1)[1]
    page_id = context.user_data.get("edit_page_id", "")
    entry = context.user_data.get("edit_entry", {})
    old_title = entry.get("title", "")
    parts = old_title.split(" - ", 1)
    desc = parts[1] if len(parts) > 1 else ""
    new_title = f"{new_type} - {desc}" if desc else new_type

    context.user_data["undo_state"] = {
        "action": "edit_type",
        "page_id": page_id,
        "old_properties": {"Name": NB.title(old_title)},
    }

    try:
        await notion_manager.update_page(page_id, {"Name": NB.title(new_title)})
        # Update the entry in context
        entry["title"] = new_title
        entry["activity_type"] = new_type
        context.user_data["edit_entry"] = entry
        # Re-render entry detail with undo
        text = render_entry_detail(entry)
        keyboard = build_entry_detail_keyboard(page_id)
        keyboard = _with_undo_button(keyboard, "Undo type change")
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(f"Error: {escape(str(e))}", reply_markup=build_back_button("act_entry:" + page_id[:36]), parse_mode="HTML")
    return ConversationHandler.END


# ── Edit Description Flow (direct execution) ─────────────────────────────────

async def edit_desc_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    page_id = query.data.split(":", 1)[1]
    context.user_data["edit_page_id"] = page_id

    await query.edit_message_text(
        "Enter new description:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(text="Back to Entry", callback_data=f"act_entry:{page_id[:36]}")],
        ]),
    )
    return EDT_ENTER_DESC


async def edit_desc_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_desc = update.message.text.strip()
    page_id = context.user_data.get("edit_page_id", "")
    entry = context.user_data.get("edit_entry", {})
    atype = entry.get("activity_type", "Other")
    old_title = entry.get("title", "")

    new_title = f"{atype} - {new_desc}" if new_desc else atype

    # Store undo state
    context.user_data["undo_state"] = {
        "action": "edit_desc",
        "page_id": page_id,
        "old_properties": {"Name": NB.title(old_title)},
    }

    status_msg = await update.message.reply_text("Updating...")
    try:
        await notion_manager.update_page(page_id, {"Name": NB.title(new_title)})
        entry["title"] = new_title
        context.user_data["edit_entry"] = entry
        text = render_entry_detail(entry)
        keyboard = build_entry_detail_keyboard(page_id)
        keyboard = _with_undo_button(keyboard, "Undo desc change")
        await status_msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"Error: {escape(str(e))}", reply_markup=build_back_button("act_entry:" + page_id[:36]), parse_mode="HTML")
    return ConversationHandler.END


# ── Edit Times Flow ──────────────────────────────────────────────────────────

async def edit_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    page_id = query.data.split(":", 1)[1]
    context.user_data["edit_page_id"] = page_id

    entry = context.user_data.get("edit_entry", {})
    start = entry.get("start")
    context.user_data["pick_date"] = (start.date().isoformat() if start else date.today().isoformat())

    await query.edit_message_text(
        "Select new START hour:",
        reply_markup=build_hour_keyboard("edt_sh", back_callback="act_view:today"),
    )
    return EDT_CHOOSE_START


async def edit_start_hour_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    hour = int(query.data.split(":", 1)[1])
    context.user_data["edt_s_hour"] = hour
    await query.edit_message_text(
        f"Select START minute for {hour:02d}:",
        reply_markup=build_minute_keyboard("edt_sm", hour),
    )
    return EDT_CHOOSE_START


async def edit_start_minute_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    hhmm = query.data.split(":", 1)[1]
    pick_date = date.fromisoformat(context.user_data.get("pick_date", date.today().isoformat()))
    new_start = hhmm_to_dt(hhmm, pick_date)
    context.user_data["edt_start"] = new_start
    context.user_data["pick_date_end"] = pick_date.isoformat()

    await query.edit_message_text(
        f"Start: {fmt_time(new_start)}\nSelect new END hour:",
        reply_markup=build_hour_keyboard("edt_eh", back_callback="act_view:today"),
    )
    return EDT_CHOOSE_END


async def edit_start_minute_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Select new START hour:", reply_markup=build_hour_keyboard("edt_sh", back_callback="act_view:today"))
    return EDT_CHOOSE_START


async def edit_end_hour_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    hour = int(query.data.split(":", 1)[1])
    context.user_data["edt_e_hour"] = hour
    await query.edit_message_text(
        f"Select END minute for {hour:02d}:",
        reply_markup=build_minute_keyboard("edt_em", hour),
    )
    return EDT_CHOOSE_END


async def edit_end_minute_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    hhmm = query.data.split(":", 1)[1]
    pick_date_end = date.fromisoformat(context.user_data.get("pick_date_end", date.today().isoformat()))
    new_start = context.user_data.get("edt_start", round_to_15(datetime.now(TZ)))
    new_end = hhmm_to_dt(hhmm, pick_date_end)
    if new_end <= new_start:
        new_end += timedelta(days=1)

    page_id = context.user_data.get("edit_page_id", "")
    entry = context.user_data.get("edit_entry", {})
    old_start = entry.get("start")
    old_end = entry.get("end")

    if old_start and old_end:
        context.user_data["undo_state"] = {
            "action": "edit_times",
            "page_id": page_id,
            "old_properties": {"Date": NB.date(old_start.isoformat(), end_iso=old_end.isoformat())},
        }

    try:
        await notion_manager.update_page(page_id, {
            "Date": NB.date(new_start.isoformat(), end_iso=new_end.isoformat()),
        })
        entry["start"] = new_start
        entry["end"] = new_end
        entry["duration_hrs"] = (new_end - new_start).total_seconds() / 3600
        context.user_data["edit_entry"] = entry
        text = render_entry_detail(entry)
        keyboard = build_entry_detail_keyboard(page_id)
        keyboard = _with_undo_button(keyboard, "Undo time change")
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(f"Error: {escape(str(e))}", reply_markup=build_back_button("act_entry:" + page_id[:36]), parse_mode="HTML")
    return ConversationHandler.END


async def edit_end_minute_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Select new END hour:", reply_markup=build_hour_keyboard("edt_eh", back_callback="act_view:today"))
    return EDT_CHOOSE_END


# ── Delete Flow (direct execution with undo) ─────────────────────────────────

async def delete_entry_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Immediately deletes entry, re-renders rolling view with undo."""
    query = update.callback_query
    await query.answer("Deleting...")
    page_id = query.data.split(":", 1)[1]

    entry = context.user_data.get("edit_entry", {})
    title = entry.get("title", "entry")

    context.user_data["undo_state"] = {
        "action": "delete",
        "page_id": page_id,
    }

    try:
        await notion_manager.delete_page(page_id)

        # Re-render rolling view with fresh data
        now = datetime.now(TZ)
        window_start = now - timedelta(hours=24)
        window_end = now
        start_str = window_start.date().isoformat()
        end_str = (window_end.date() + timedelta(days=1)).isoformat()
        fresh_entries = await notion_manager.query_activity_entries(start_str, end_str, sort_ascending=False)
        fresh_entries = [e for e in fresh_entries if e.get("start") and e["start"] >= window_start and e["start"] < window_end]
        fresh_entries.sort(key=lambda e: e.get("start", datetime.min))
        context.user_data["view_entries"] = {e["page_id"]: e for e in fresh_entries}

        text = render_rolling_view(fresh_entries, window_start, window_end, [])
        if len(text) > 3800:
            text = text[:3800] + "\n..."

        # Add undo banner
        undo_text = f"\n\n{bold('Deleted:')} {escape(title)}  "
        keyboard_rows = [
            [InlineKeyboardButton(text="Undo delete", callback_data="undo_action")],
        ]
        # Add gap buttons
        for i in range(len(fresh_entries) - 1):
            end = fresh_entries[i].get("end")
            next_start = fresh_entries[i + 1].get("start")
            if end and next_start:
                gap_hrs = (next_start - end).total_seconds() / 3600
                if gap_hrs >= 0.5:
                    keyboard_rows.append([InlineKeyboardButton(
                        text=f"Fill gap: {fmt_time(end)}-{fmt_time(next_start)} ({fmt_dur(gap_hrs)})",
                        callback_data=f"act_gap:{end.strftime('%Y%m%dT%H%M')}-{next_start.strftime('%Y%m%dT%H%M')}",
                    )])
        keyboard_rows.append([
            InlineKeyboardButton(text="+ New Entry", callback_data="menu:activity"),
            InlineKeyboardButton(text="Back", callback_data="sub:activity"),
        ])

        await query.edit_message_text(text + undo_text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Delete failed: {e}", exc_info=True)
        await query.edit_message_text(f"Error: {escape(str(e))}", reply_markup=build_back_button("act_entry:" + page_id[:36]), parse_mode="HTML")


# ── Adjacent Entry Flow ──────────────────────────────────────────────────────

async def add_adjacent_before(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Start a new entry that ends where the selected entry starts.
    New entry end = selected entry start. User picks start time.
    """
    query = update.callback_query
    await query.answer()
    logger.info(f"[ADJ_BEFORE] Callback data: {query.data}")

    entry = context.user_data.get("edit_entry", {})
    ref_start = entry.get("start")
    logger.info(f"[ADJ_BEFORE] edit_entry keys: {list(entry.keys())}, ref_start: {ref_start}")
    if not ref_start:
        logger.warning("[ADJ_BEFORE] Entry has no start time!")
        await query.edit_message_text("Entry has no start time.", reply_markup=build_back_button("act_view:today"))
        return ConversationHandler.END

    # Set end time = selected entry's start
    context.user_data["act_end"] = ref_start
    context.user_data["pick_date"] = ref_start.date().isoformat()

    # Pre-fetch activity types
    types = await notion_manager.get_activity_types()
    context.user_data["activity_types"] = [t["name"] for t in types] if types else [
        "Work", "Workout", "Shadow Work", "Trading", "Networking",
        "Meeting", "Meditation", "Brain Games", "Sleep", "Chores",
        "Recreation", "Study", "Socialize", "Content Creation",
    ]

    # Fetch 48h entries for context
    now = datetime.now(TZ)
    h48_start = (now - timedelta(hours=48)).date()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    entries_48h = await notion_manager.query_activity_entries(
        h48_start.isoformat(), tomorrow
    )
    entries_48h.sort(key=lambda e: e.get("start", datetime.min))
    context.user_data["recent_entries"] = entries_48h

    # Show start time picker with the constraint
    ref_str = _fmt_time_with_date(ref_start, now)
    suggestions = _compute_time_suggestions(entries_48h, now, None)

    # Filter suggestions to only those that end before ref_start
    filtered = []
    for s in suggestions:
        if s.get("start_only"):
            continue
        end_dt = _parse_compact_dt(s["end_hhmm"])
        if end_dt <= ref_start:
            filtered.append(s)

    # Add direct options: ref_start - various durations
    for mins in [15, 30, 45, 60, 90, 120]:
        start_dt = round_to_15(ref_start - timedelta(minutes=mins))
        if start_dt.date() < ref_start.date():
            s_str = _fmt_time_with_date(start_dt, now)
        else:
            s_str = fmt_time(start_dt)
        filtered.append({
            "label": f"{s_str} → {ref_str} ({fmt_dur(mins / 60)})",
            "start_hhmm": start_dt.strftime("%Y%m%dT%H%M"),
            "end_hhmm": ref_start.strftime("%Y%m%dT%H%M"),
            "start_only": False,
        })

    timeline = render_timeline_with_marker(entries_48h, ref_start - timedelta(hours=1), ref_start, "NEW ENTRY")
    text = f"{timeline}\n\nAdd entry BEFORE <b>{ref_str}</b>\nSelect START time:"

    keyboard_rows = []
    for s in filtered:
        cb = f"s_sug:{s['start_hhmm']}-{s['end_hhmm']}"
        keyboard_rows.append([InlineKeyboardButton(text=s["label"], callback_data=cb)])
    keyboard_rows.append([InlineKeyboardButton(text="Custom time...", callback_data="s_sug:custom")])
    keyboard_rows.append([InlineKeyboardButton(text="Back to Entry", callback_data=f"act_entry:{entry.get('page_id', '')[:36]}")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
    return CHOOSE_START


async def add_adjacent_after(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Start a new entry that begins where the selected entry ends.
    New entry start = selected entry end. User picks end time.
    """
    query = update.callback_query
    await query.answer()

    entry = context.user_data.get("edit_entry", {})
    ref_end = entry.get("end")
    if not ref_end:
        await query.edit_message_text("Entry has no end time.", reply_markup=build_back_button("act_view:today"))
        return ConversationHandler.END

    # Set start time = selected entry's end
    context.user_data["act_start"] = ref_end
    context.user_data["pick_date"] = ref_end.date().isoformat()

    # Pre-fetch activity types
    types = await notion_manager.get_activity_types()
    context.user_data["activity_types"] = [t["name"] for t in types] if types else [
        "Work", "Workout", "Shadow Work", "Trading", "Networking",
        "Meeting", "Meditation", "Brain Games", "Sleep", "Chores",
        "Recreation", "Study", "Socialize", "Content Creation",
    ]

    # Fetch 48h entries for context
    now = datetime.now(TZ)
    h48_start = (now - timedelta(hours=48)).date()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    entries_48h = await notion_manager.query_activity_entries(
        h48_start.isoformat(), tomorrow
    )
    entries_48h.sort(key=lambda e: e.get("start", datetime.min))
    context.user_data["recent_entries"] = entries_48h

    # Show end time picker
    ref_str = _fmt_time_with_date(ref_end, now)
    suggestions = []

    # Duration-based end times from ref_end
    for mins in [15, 30, 45, 60, 90, 120]:
        end_dt = round_to_15(ref_end + timedelta(minutes=mins))
        e_str = _fmt_time_with_date(end_dt, now)
        suggestions.append({
            "label": f"{ref_str} → {e_str} ({fmt_dur(mins / 60)})",
            "start_hhmm": ref_end.strftime("%Y%m%dT%H%M"),
            "end_hhmm": end_dt.strftime("%Y%m%dT%H%M"),
            "start_only": False,
        })

    # "Until next entry" suggestion
    for e in entries_48h:
        e_start = e.get("start")
        if e_start and e_start > ref_end:
            gap_hrs = (e_start - ref_end).total_seconds() / 3600
            e_str = _fmt_time_with_date(e_start, now)
            suggestions.append({
                "label": f"{ref_str} → {e_str} ({fmt_dur(gap_hrs)}) — until next",
                "start_hhmm": ref_end.strftime("%Y%m%dT%H%M"),
                "end_hhmm": e_start.strftime("%Y%m%dT%H%M"),
                "start_only": False,
            })
            break

    timeline = render_timeline_with_marker(entries_48h, ref_end, ref_end + timedelta(hours=1), "NEW ENTRY")
    text = f"{timeline}\n\nAdd entry AFTER <b>{ref_str}</b>\nSelect END time:"

    keyboard_rows = []
    for s in suggestions:
        cb = f"e_sug:{s['start_hhmm']}-{s['end_hhmm']}"
        keyboard_rows.append([InlineKeyboardButton(text=s["label"], callback_data=cb)])
    keyboard_rows.append([InlineKeyboardButton(text="Custom time...", callback_data="e_sug:custom")])
    keyboard_rows.append([InlineKeyboardButton(text="Back to Entry", callback_data=f"act_entry:{entry.get('page_id', '')[:36]}")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
    return CHOOSE_END


# ── Fast-Add from Gap ────────────────────────────────────────────────────────

async def fast_add_from_gap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Starts a new entry with pre-filled start/end times from a gap button.
    Callback data: act_gap:YYYYMMDDTHHMM-YYYYMMDDTHHMM (compact ISO format)
    """
    query = update.callback_query
    await query.answer()

    raw = query.data.split(":", 1)[1]
    parts = raw.split("-")
    if len(parts) != 2:
        await query.edit_message_text("Invalid gap data.", reply_markup=build_back_button("act_view:today"))
        return ConversationHandler.END

    # Parse compact ISO datetime format (YYYYMMDDTHHMM)
    try:
        start_dt = _parse_compact_dt(parts[0])
        end_dt = _parse_compact_dt(parts[1])
    except Exception:
        await query.edit_message_text("Invalid gap data.", reply_markup=build_back_button("act_view:today"))
        return ConversationHandler.END

    context.user_data["pick_date"] = start_dt.date().isoformat()
    context.user_data["pick_date_end"] = end_dt.date().isoformat()

    context.user_data["act_start"] = start_dt
    context.user_data["act_end"] = end_dt

    # Fetch activity types
    types = await notion_manager.get_activity_types()
    type_names = [t["name"] for t in types] if types else [
        "Work", "Workout", "Shadow Work", "Trading", "Networking",
        "Meeting", "Meditation", "Brain Games", "Sleep", "Chores",
        "Recreation", "Study", "Socialize", "Content Creation",
    ]
    context.user_data["activity_types"] = type_names

    dur_hrs = (end_dt - start_dt).total_seconds() / 3600

    # Fetch entries around the gap for timeline context
    entry_date = start_dt.date()
    today_start = datetime.combine(entry_date, datetime.min.time(), tzinfo=TZ)
    today_end = datetime.combine(entry_date + timedelta(days=1), datetime.min.time(), tzinfo=TZ)
    today_entries = await notion_manager.query_activity_entries(
        today_start.date().isoformat(), today_end.date().isoformat()
    )
    context.user_data["recent_entries"] = today_entries

    timeline = render_timeline_with_marker(today_entries, start_dt, end_dt, "NEW ENTRY")

    text = (
        f"{timeline}\n\n"
        f"Fill gap: <code>{fmt_time(start_dt)} - {fmt_time(end_dt)}</code> ({fmt_dur(dur_hrs)})\n\n"
        f"Select activity type:"
    )
    keyboard = build_grid_keyboard(type_names, "act_type", row_width=2)
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="Back to Activity", callback_data="act_back_dash")])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")

    # Set a flag so we skip start/end time pickers and go straight to notes
    context.user_data["fast_add"] = True
    return CHOOSE_TYPE


# ── Gap Report ───────────────────────────────────────────────────────────────

async def show_gaps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Checking gaps...")

    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    entries = await notion_manager.query_activity_entries(week_ago, tomorrow)

    if len(entries) < 2:
        await query.edit_message_text("Not enough entries.", reply_markup=build_back_button("sub:activity"))
        return

    gaps = []
    for i in range(len(entries) - 1):
        curr_end = entries[i].get("end")
        next_start = entries[i + 1].get("start")
        if curr_end and next_start:
            gap_hrs = (next_start - curr_end).total_seconds() / 3600
            if gap_hrs >= 4:
                gaps.append({
                    "date": curr_end.strftime("%a %b %d"),
                    "start": curr_end.strftime("%H:%M"),
                    "end": next_start.strftime("%H:%M"),
                    "hours": gap_hrs,
                })

    text = render_gap_report(gaps)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="View Today", callback_data="act_view:today")],
        [InlineKeyboardButton(text="Back", callback_data="sub:activity")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


# ── Periodic Gap Alert Job ───────────────────────────────────────────────────

async def check_activity_gaps(context: ContextTypes.DEFAULT_TYPE) -> None:
    from cache import bot_cache

    if await bot_cache.get("last_gap_alert"):
        return

    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    entries = await notion_manager.query_activity_entries(week_ago, tomorrow)
    if len(entries) < 2:
        return

    gaps = []
    for i in range(len(entries) - 1):
        curr_end = entries[i].get("end")
        next_start = entries[i + 1].get("start")
        if curr_end and next_start:
            gap_hrs = (next_start - curr_end).total_seconds() / 3600
            if gap_hrs >= 4:
                gaps.append(f"  {curr_end.strftime('%b %d')} {curr_end.strftime('%H:%M')}-{next_start.strftime('%H:%M')} ({fmt_dur(gap_hrs)})")

    if not gaps:
        return

    chat_id = context.bot_data.get("user_chat_id")
    if chat_id:
        text = f"Gap Alert — {len(gaps)} gap(s) >= 4h:\n" + "\n".join(gaps[:10])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="View Today", callback_data="act_view:today")],
        ])
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)

    await bot_cache.set("last_gap_alert", True, expire=3600)
