# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/cli/simulate.py
"""
Session-based Telegram bot simulator for AI agents.

Maintains a state machine mirroring the Telegram bot's conversation states.
Each state has a "screen builder" that generates text and buttons the bot would send.
AI agents navigate via callback_data selections, and the CLI returns screens.

State machine:
    start -> viewing_dashboard
          -> viewing_activity_log -> viewing_entry_detail -> editing_type/desc/time/notes/deleting
          -> logging_activity -> picking_type -> picking_time -> entering_desc -> confirming
          -> viewing_gaps -> confirming (fast_add)
          -> viewing_financial_log -> entering_amount -> picking_category -> confirming
          -> viewing_diet_log -> picking_meal -> entering_desc -> confirming
          -> viewing_journal_menu -> subjective/relational/systemic chains -> confirming
"""

import asyncio
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import typer

from cli.format import output
from services.activity import (
    get_activity_entries, get_entry_detail, get_activity_types,
    get_activity_stats, get_gaps, save_activity_entry,
    update_entry_type, update_entry_time, delete_entry, calculate_offset,
)
from services.dashboard import get_dashboard_data
from services.diet import get_diet_entries, get_meal_types, save_diet_entry
from services.financial import (
    get_financial_entries, get_financial_categories, save_financial_entry,
)
from services.journal import (
    get_subjective_entries, get_relational_entries, get_systemic_entries,
    save_subjective_entry, save_relational_entry, save_systemic_entry,
)

logger = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=5, minutes=30))
SESSIONS_DIR = os.path.expanduser("~/.lifeos/cli_sessions")

app = typer.Typer(help="Simulate Telegram bot conversation flow")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Convert Telegram HTML to plain CLI text."""
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<i>", "*").replace("</i>", "*")
    text = text.replace("<code>", "`").replace("</code>", "`")
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2 (\1)", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def _session_path(session_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{session_id}.json")


def _load_session(session_id: str) -> dict:
    path = _session_path(session_id)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _save_session(sd: dict) -> None:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(_session_path(sd["id"]), "w") as f:
        json.dump(sd, f, indent=2, default=str)


def _new_session_id() -> str:
    return f"cli_{secrets.token_hex(8)}"


def _make_screen(sd: dict, text: str, buttons: list) -> dict:
    return {
        "text": text,
        "buttons": buttons,
        "session": sd["id"],
        "state": sd["state"],
        "timestamp": datetime.now(TZ).isoformat(),
    }


def _err_screen(sd: dict, msg: str) -> dict:
    return {
        "text": f"Error: {msg}",
        "buttons": [{"text": "Dashboard", "action": "dashboard"}],
        "session": sd["id"] if sd else "unknown",
        "state": sd.get("state", "error") if sd else "error",
        "timestamp": datetime.now(TZ).isoformat(),
    }


def _run_async(coro) -> Any:
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Screen Builders ────────────────────────────────────────────────────────────

def _build_dashboard_screen(sd: dict) -> dict:
    stats = _run_async(get_activity_stats())
    lines = [
        "LifeOS Dashboard",
        "",
        f"48h: {stats['count_48h']} entries, {stats['total_48h']:.1f}h tracked",
        f" 7d: {stats['count_7d']} entries, {stats['total_7d']:.1f}h tracked",
        f"30d: {stats['count_30d']} entries, {stats['total_30d']:.1f}h tracked",
    ]
    if stats.get("category_breakdown"):
        lines.append("")
        lines.append("Top Categories (7d):")
        for cat, hrs in stats["category_breakdown"][:5]:
            lines.append(f"  {cat}: {hrs:.1f}h")
    sd["state"] = "viewing_dashboard"
    return _make_screen(sd, "\n".join(lines), [
        {"text": "Activity Log", "action": "activity_log"},
        {"text": "Log Activity", "action": "log_new"},
        {"text": "Gaps (7d)", "action": "gaps"},
        {"text": "Financial Log", "action": "financial_log"},
        {"text": "Diet Log", "action": "diet_log"},
        {"text": "Journal", "action": "journal_menu"},
    ])


def _build_activity_log_screen(sd: dict, date_str: Optional[str] = None) -> dict:
    if not date_str:
        date_str = datetime.now(TZ).strftime("%Y-%m-%d")
    entries = _run_async(get_activity_entries(date_from=date_str, date_to=date_str, sort_ascending=True))
    lines = [f"Activity Log -- {date_str}", ""]
    if entries:
        for e in entries:
            s, en = e.get("start"), e.get("end")
            title = e.get("title", "") or e.get("activity_type", "")
            dur = e.get("duration_hrs", 0)
            ts = f"{s.strftime('%H:%M')}-{en.strftime('%H:%M')}" if s and en else ""
            lines.append(f"  {ts}  {title}  ({dur:.1f}h)")
    else:
        lines.append("  No entries for this day.")
    sd["context"]["current_date"] = date_str
    sd["state"] = "viewing_activity_log"
    buttons = [{"text": "+ Log New", "action": "log_new"}]
    for e in entries[:20]:
        pid = e.get("page_id", "")
        lbl = (e.get("title", "") or e.get("activity_type", ""))[:30] or "Untitled"
        buttons.append({"text": lbl, "action": f"act_entry:{pid}"})
    buttons.append({"text": "Dashboard", "action": "dashboard"})
    return _make_screen(sd, "\n".join(lines), buttons)


def _build_entry_detail_screen(sd: dict, page_id: str) -> dict:
    detail = _run_async(get_entry_detail(page_id))
    if not detail.get("found"):
        return _err_screen(sd, f"Entry not found: {detail.get('error', 'unknown')}")
    entry = detail["entry"]
    s, en = entry.get("start"), entry.get("end")
    title = entry.get("title", "") or entry.get("activity_type", "")
    dur = entry.get("duration_hrs", 0)
    ts = f"{s.strftime('%H:%M')} - {en.strftime('%H:%M')} ({dur:.1f}h)" if s and en else ""
    sd["context"]["selected_entry"] = page_id
    sd["state"] = "viewing_entry_detail"
    return _make_screen(sd, f"Entry Detail\n  {title}\n  {ts}", [
        {"text": "Edit Type", "action": f"edt_type:{page_id}"},
        {"text": "Edit Time", "action": f"edt_time:{page_id}"},
        {"text": "Edit Description", "action": f"edt_desc:{page_id}"},
        {"text": "Delete", "action": f"edt_del:{page_id}"},
        {"text": "Back", "action": "activity_log"},
    ])


def _build_type_picker_screen(sd: dict) -> dict:
    types = _run_async(get_activity_types())
    sd["state"] = "picking_type"
    return _make_screen(sd, "Select activity type:", [
        {"text": t, "action": f"pick_type:{t}"} for t in types
    ] + [{"text": "Cancel", "action": "dashboard"}])


def _build_time_picker_screen(sd: dict) -> dict:
    sd["state"] = "picking_time"
    return _make_screen(sd, "Enter time range (e.g. 09:00-11:00), or type custom:", [
        {"text": "Custom time...", "action": "pick_time:custom"},
        {"text": "Cancel", "action": "dashboard"},
    ])


def _build_desc_input_screen(sd: dict) -> dict:
    sd["state"] = "entering_desc"
    return _make_screen(sd, "Enter description (or /skip to leave blank):", [
        {"text": "Skip", "action": "enter_desc:skip"},
        {"text": "Cancel", "action": "dashboard"},
    ])


def _build_confirm_screen(sd: dict, text: str, confirm_action: str) -> dict:
    sd["state"] = "confirming"
    return _make_screen(sd, f"{text}\n\nConfirm this entry?", [
        {"text": "Yes", "action": confirm_action},
        {"text": "No", "action": "dashboard"},
    ])


def _build_gaps_screen(sd: dict) -> dict:
    week_ago = (datetime.now(TZ) - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    entries = _run_async(get_activity_entries(date_from=week_ago, date_to=today, sort_ascending=True))
    gaps = get_gaps(entries, threshold_minutes=30)
    lines = [f"Gap Report -- {len(gaps)} gap(s) found", ""]
    if gaps:
        for i, g in enumerate(gaps[:15]):
            ss = g["start"].strftime("%H:%M") if hasattr(g["start"], "strftime") else str(g["start"])
            se = g["end"].strftime("%H:%M") if hasattr(g["end"], "strftime") else str(g["end"])
            lines.append(f"  {i+1}. {ss} - {se} ({g['hours']:.1f}h)")
    else:
        lines.append("  No gaps found.")
    sd["state"] = "viewing_gaps"
    buttons = [{"text": f"Fill Gap {i+1}", "action": f"fast_add:{i}"} for i, g in enumerate(gaps[:10])]
    buttons.append({"text": "Dashboard", "action": "dashboard"})
    return _make_screen(sd, "\n".join(lines), buttons)


def _build_financial_log_screen(sd: dict) -> dict:
    entries = _run_async(get_financial_entries(limit=20))
    lines = ["Financial Log", ""]
    if entries:
        for e in entries:
            lines.append(f"  {e.get('date','')}  {e.get('type','')}: {e.get('category','')}  ${e.get('amount',0):.2f}")
    else:
        lines.append("  No entries found.")
    sd["state"] = "viewing_financial_log"
    return _make_screen(sd, "\n".join(lines), [
        {"text": "+ Log Transaction", "action": "log_financial"},
        {"text": "Dashboard", "action": "dashboard"},
    ])


def _build_financial_amount_screen(sd: dict) -> dict:
    sd["state"] = "entering_amount"
    return _make_screen(sd, "Enter amount (e.g. 25.50):", [{"text": "Cancel", "action": "dashboard"}])


def _build_financial_category_screen(sd: dict) -> dict:
    cats = _run_async(get_financial_categories())
    sd["state"] = "picking_category"
    return _make_screen(sd, "Select category:", [
        {"text": c, "action": f"pick_fin_cat:{c}"} for c in cats
    ] + [{"text": "Cancel", "action": "dashboard"}])


def _build_diet_log_screen(sd: dict) -> dict:
    entries = _run_async(get_diet_entries(limit=20))
    lines = ["Diet Log", ""]
    if entries:
        for e in entries:
            lines.append(f"  {e.get('date','')}  {e.get('meal_type','')}: {e.get('description','')}")
    else:
        lines.append("  No entries found.")
    sd["state"] = "viewing_diet_log"
    return _make_screen(sd, "\n".join(lines), [
        {"text": "+ Log Meal", "action": "log_diet"},
        {"text": "Dashboard", "action": "dashboard"},
    ])


def _build_meal_picker_screen(sd: dict) -> dict:
    meals = _run_async(get_meal_types())
    sd["state"] = "picking_meal"
    return _make_screen(sd, "Select meal type:", [
        {"text": m, "action": f"pick_meal:{m}"} for m in meals
    ] + [{"text": "Cancel", "action": "dashboard"}])


def _build_journal_menu_screen(sd: dict) -> dict:
    sd["state"] = "viewing_journal_menu"
    return _make_screen(sd, "Journal\n\nChoose journal type:", [
        {"text": "Subjective (Energy/Focus/Happiness)", "action": "journal_subjective"},
        {"text": "Relational (Person/Connection)", "action": "journal_relational"},
        {"text": "Systemic (Bottlenecks/Actions)", "action": "journal_systemic"},
        {"text": "Dashboard", "action": "dashboard"},
    ])


def _build_rating_screen(sd: dict, prompt: str, callback_prefix: str, state: str) -> dict:
    sd["state"] = state
    return _make_screen(sd, prompt, [
        {"text": str(n), "action": f"{callback_prefix}:{n}"} for n in range(1, 11)
    ] + [{"text": "Skip", "action": f"{callback_prefix}:skip"}])


def _build_text_input_screen(sd: dict, prompt: str, state: str, skip_action: str = "") -> dict:
    sd["state"] = state
    buttons = []
    if skip_action:
        buttons.append({"text": "Skip", "action": skip_action})
    buttons.append({"text": "Cancel", "action": "dashboard"})
    return _make_screen(sd, prompt, buttons)


# ── Action Handlers ────────────────────────────────────────────────────────────

# Each handler receives (session_data, raw_action, input_text) and returns a screen dict.


def _handle_dashboard(sd, action, input_text=None):
    return _build_dashboard_screen(sd)


def _handle_activity_log(sd, action, input_text=None):
    return _build_activity_log_screen(sd, sd.get("context", {}).get("current_date"))


def _handle_entry_detail(sd, action, input_text=None):
    parts = action.split(":", 1)
    return _build_entry_detail_screen(sd, parts[1] if len(parts) > 1 else "")


def _handle_log_new(sd, action, input_text=None):
    sd["context"]["pending_data"] = {}
    return _build_type_picker_screen(sd)


def _handle_pick_type(sd, action, input_text=None):
    parts = action.split(":", 1)
    atype = parts[1] if len(parts) > 1 else (input_text or "")
    sd["context"].setdefault("pending_data", {})["activity_type"] = atype
    return _build_time_picker_screen(sd)


def _handle_pick_time(sd, action, input_text=None):
    # action: pick_time:09:00-11:00 or act_gap:HHMM-HHMM
    parts = action.split(":", 1)
    tval = parts[1] if len(parts) > 1 else (input_text or "")
    sd["context"].setdefault("pending_data", {})["time_range"] = tval
    return _build_desc_input_screen(sd)


def _handle_enter_desc(sd, action, input_text=None):
    parts = action.split(":", 1)
    desc = parts[1] if len(parts) > 1 else (input_text or "")
    if desc == "skip":
        desc = ""
    sd["context"].setdefault("pending_data", {})["notes"] = desc
    pd = sd["context"]["pending_data"]
    confirm = f"Log: {pd.get('activity_type','?')}"
    if desc:
        confirm += f" - {desc}"
    confirm += f"\nTime: {pd.get('time_range','?')}"
    return _build_confirm_screen(sd, confirm, "confirm_save")


def _handle_confirm_save(sd, action, input_text=None):
    pd = sd["context"].get("pending_data", {})
    atype = pd.get("activity_type", "Unknown")
    notes = pd.get("notes", "")
    tr = pd.get("time_range", "")
    now = datetime.now(TZ)
    start, end = now, now + timedelta(hours=1)
    if tr and tr != "custom":
        try:
            pts = tr.replace(":", "").split("-")
            if len(pts) == 2:
                sh, sm = int(pts[0][:2]), int(pts[0][2:4]) if len(pts[0]) > 2 else 0
                eh, em = int(pts[1][:2]), int(pts[1][2:4]) if len(pts[1]) > 2 else 0
                start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
                if end <= start:
                    end = start + timedelta(hours=1)
        except (ValueError, IndexError):
            pass
    result = _run_async(save_activity_entry(activity_type=atype, start=start, end=end, notes=notes))
    text = f"Logged: {atype}" if result.get("success") else f"Error: {result.get('error','unknown')}"
    sd["context"]["pending_data"] = {}
    sd["state"] = "viewing_dashboard"
    return _make_screen(sd, text, [{"text": "Dashboard", "action": "dashboard"}])


def _handle_gaps(sd, action, input_text=None):
    return _build_gaps_screen(sd)


def _handle_fast_add(sd, action, input_text=None):
    parts = action.split(":", 1)
    idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    sd["context"]["pending_data"] = {"gap_index": idx, "activity_type": "Work"}
    return _build_type_picker_screen(sd)


def _handle_financial_log(sd, action, input_text=None):
    return _build_financial_log_screen(sd)


def _handle_log_financial(sd, action, input_text=None):
    sd["context"]["pending_data"] = {"type": "Expense"}
    return _build_financial_amount_screen(sd)


def _handle_financial_amount(sd, action, input_text=None):
    parts = action.split(":", 1)
    amt = parts[1] if len(parts) > 1 else (input_text or "0")
    sd["context"]["pending_data"]["amount"] = float(amt.replace("$", "")) if amt.replace("$", "").replace(".", "").isdigit() else 0.0
    return _build_financial_category_screen(sd)


def _handle_pick_fin_cat(sd, action, input_text=None):
    parts = action.split(":", 1)
    cat = parts[1] if len(parts) > 1 else (input_text or "")
    pd = sd["context"].get("pending_data", {})
    result = _run_async(save_financial_entry(type_=pd.get("type", "Expense"), amount=pd.get("amount", 0), category=cat))
    text = f"Logged {pd.get('type','?')}: ${pd.get('amount',0):.2f} ({cat})" if result.get("success") else f"Error: {result.get('error','unknown')}"
    sd["context"]["pending_data"] = {}
    sd["state"] = "viewing_dashboard"
    return _make_screen(sd, text, [{"text": "Dashboard", "action": "dashboard"}])


def _handle_diet_log(sd, action, input_text=None):
    return _build_diet_log_screen(sd)


def _handle_log_diet(sd, action, input_text=None):
    sd["context"]["pending_data"] = {}
    return _build_meal_picker_screen(sd)


def _handle_pick_meal(sd, action, input_text=None):
    parts = action.split(":", 1)
    sd["context"]["pending_data"]["meal_type"] = parts[1] if len(parts) > 1 else (input_text or "")
    sd["state"] = "entering_diet_desc"
    return _make_screen(sd, "Describe what you ate:", [{"text": "Cancel", "action": "dashboard"}])


def _handle_diet_desc(sd, action, input_text=None):
    parts = action.split(":", 1)
    desc = parts[1] if len(parts) > 1 else (input_text or "")
    mt = sd["context"].get("pending_data", {}).get("meal_type", "Meal")
    result = _run_async(save_diet_entry(meal_type=mt, meal_description=desc))
    text = result.get("message", f"Logged {mt}: {desc}") if result.get("success") else f"Error: {result.get('error','unknown')}"
    sd["context"]["pending_data"] = {}
    sd["state"] = "viewing_dashboard"
    return _make_screen(sd, text, [{"text": "Dashboard", "action": "dashboard"}])


def _handle_journal_menu(sd, action, input_text=None):
    return _build_journal_menu_screen(sd)


def _handle_journal_subjective(sd, action, input_text=None):
    sd["context"]["pending_data"] = {"journal_type": "subjective"}
    return _build_rating_screen(sd, "Rate your energy level (1-10):", "energy", "entering_energy")


def _handle_energy(sd, action, input_text=None):
    parts = action.split(":", 1)
    val = parts[1] if len(parts) > 1 else "skip"
    if val != "skip":
        sd["context"]["pending_data"]["energy"] = int(val)
    return _build_rating_screen(sd, "Rate your focus level (1-10):", "focus", "entering_focus")


def _handle_focus(sd, action, input_text=None):
    parts = action.split(":", 1)
    val = parts[1] if len(parts) > 1 else "skip"
    if val != "skip":
        sd["context"]["pending_data"]["focus"] = int(val)
    return _build_rating_screen(sd, "Rate your happiness level (1-10):", "happiness", "entering_happiness")


def _handle_happiness(sd, action, input_text=None):
    parts = action.split(":", 1)
    val = parts[1] if len(parts) > 1 else "skip"
    if val != "skip":
        sd["context"]["pending_data"]["happiness"] = int(val)
    pd = sd["context"].get("pending_data", {})
    result = _run_async(save_subjective_entry(energy=pd.get("energy"), focus=pd.get("focus"), happiness=pd.get("happiness"), gratitude=""))
    text = result.get("message", "Subjective journal logged.") if result.get("success") else f"Error: {result.get('message', 'unknown')}"
    sd["context"]["pending_data"] = {}
    sd["state"] = "viewing_dashboard"
    return _make_screen(sd, text, [{"text": "Dashboard", "action": "dashboard"}])


def _handle_journal_relational(sd, action, input_text=None):
    sd["context"]["pending_data"] = {"journal_type": "relational"}
    return _build_text_input_screen(sd, "Enter the person's name:", "entering_person", "rel_person:skip")


def _handle_rel_person(sd, action, input_text=None):
    parts = action.split(":", 1)
    person = parts[1] if len(parts) > 1 else (input_text or "")
    if person != "skip":
        sd["context"]["pending_data"]["person"] = person
    return _build_rating_screen(sd, "Rate connection quality (1-10):", "rel_quality", "entering_quality")


def _handle_rel_quality(sd, action, input_text=None):
    parts = action.split(":", 1)
    val = parts[1] if len(parts) > 1 else "skip"
    quality = int(val) if val != "skip" else None
    pd = sd["context"].get("pending_data", {})
    result = _run_async(save_relational_entry(person=pd.get("person", "Unknown"), connection_quality=quality, insights=""))
    text = result.get("message", f"Relational journal: {pd.get('person','?')}") if result.get("success") else f"Error: {result.get('message', 'unknown')}"
    sd["context"]["pending_data"] = {}
    sd["state"] = "viewing_dashboard"
    return _make_screen(sd, text, [{"text": "Dashboard", "action": "dashboard"}])


def _handle_journal_systemic(sd, action, input_text=None):
    sd["context"]["pending_data"] = {"journal_type": "systemic"}
    return _build_text_input_screen(sd, "Describe current bottlenecks or friction points:", "entering_bottlenecks", "sys_bottleneck:skip")


def _handle_sys_bottleneck(sd, action, input_text=None):
    parts = action.split(":", 1)
    bt = parts[1] if len(parts) > 1 else (input_text or "")
    if bt != "skip":
        sd["context"]["pending_data"]["bottlenecks"] = bt
    return _build_text_input_screen(sd, "List actionable changes or solutions:", "entering_actions", "sys_actions:skip")


def _handle_sys_actions(sd, action, input_text=None):
    parts = action.split(":", 1)
    at = parts[1] if len(parts) > 1 else (input_text or "")
    pd = sd["context"].get("pending_data", {})
    result = _run_async(save_systemic_entry(bottlenecks=pd.get("bottlenecks", ""), actionable_items=at if at != "skip" else ""))
    text = result.get("message", "Systemic journal logged.") if result.get("success") else f"Error: {result.get('message', 'unknown')}"
    sd["context"]["pending_data"] = {}
    sd["state"] = "viewing_dashboard"
    return _make_screen(sd, text, [{"text": "Dashboard", "action": "dashboard"}])


def _handle_back(sd, action, input_text=None):
    return _build_dashboard_screen(sd)


# ── Action Routing ─────────────────────────────────────────────────────────────

# Exact match routes: (target_state, handler_fn)
ACTION_ROUTES: Dict[str, Tuple[str, Any]] = {
    "dashboard": ("viewing_dashboard", _handle_dashboard),
    "activity_log": ("viewing_activity_log", _handle_activity_log),
    "log_new": ("logging_activity", _handle_log_new),
    "gaps": ("viewing_gaps", _handle_gaps),
    "financial_log": ("viewing_financial_log", _handle_financial_log),
    "diet_log": ("viewing_diet_log", _handle_diet_log),
    "journal_menu": ("viewing_journal_menu", _handle_journal_menu),
    "back": ("viewing_dashboard", _handle_back),
    "cancel": ("viewing_dashboard", _handle_back),
    "confirm_save": ("saving", _handle_confirm_save),
    "log_financial": ("logging_financial", _handle_log_financial),
    "log_diet": ("logging_diet", _handle_log_diet),
    "journal_subjective": ("logging_subjective", _handle_journal_subjective),
    "journal_relational": ("logging_relational", _handle_journal_relational),
    "journal_systemic": ("logging_systemic", _handle_journal_systemic),
}

# Prefix-based routes: action starts with prefix -> handler
PREFIX_ROUTES: Dict[str, Any] = {
    "act_entry:": _handle_entry_detail,
    "entry_detail:": _handle_entry_detail,
    "pick_type:": _handle_pick_type,
    "pick_time:": _handle_pick_time,
    "act_gap:": _handle_pick_time,
    "enter_desc:": _handle_enter_desc,
    "fast_add:": _handle_fast_add,
    "fin_amount:": _handle_financial_amount,
    "pick_fin_cat:": _handle_pick_fin_cat,
    "pick_meal:": _handle_pick_meal,
    "diet_desc:": _handle_diet_desc,
    "energy:": _handle_energy,
    "focus:": _handle_focus,
    "happiness:": _handle_happiness,
    "rel_person:": _handle_rel_person,
    "rel_quality:": _handle_rel_quality,
    "sys_bottleneck:": _handle_sys_bottleneck,
    "sys_actions:": _handle_sys_actions,
    "edt_type:": _handle_entry_detail,
    "edt_time:": _handle_entry_detail,
    "edt_desc:": _handle_entry_detail,
    "edt_del:": _handle_entry_detail,
    "act_view:": _handle_activity_log,
    "act_gaps:": _handle_gaps,
    "menu:main": _handle_dashboard,
    "menu:activity": _handle_log_new,
    "menu:financial": _handle_log_financial,
    "menu:diet": _handle_log_diet,
    "menu:subjective_journal": _handle_journal_subjective,
    "menu:relational_journal": _handle_journal_relational,
    "menu:systemic_journal": _handle_journal_systemic,
    "sub:activity": _handle_activity_log,
    "sub:financial": _handle_financial_log,
    "sub:diet": _handle_diet_log,
    "sub:journal": _handle_journal_menu,
}


def _resolve_handler(action: str):
    """Find the handler function for an action string (exact then prefix match)."""
    if action in ACTION_ROUTES:
        return ACTION_ROUTES[action][1]
    for prefix, handler in PREFIX_ROUTES.items():
        if action.startswith(prefix):
            return handler
    # Check if a known alias exists (for "log_new" -> _handle_log_new, etc.)
    for key, (_, handler) in ACTION_ROUTES.items():
        if action == key:
            return handler
    return None


# ── CLI Commands ───────────────────────────────────────────────────────────────


@app.command("start")
def start_session(
    session: Optional[str] = typer.Option(None, "--session", help="Session ID (auto-generate if omitted)"),
    format: str = typer.Option("toon", "--format", help="Output format: toon, json, text"),
):
    """Start a new CLI session. Returns initial screen (dashboard)."""
    sid = session or _new_session_id()
    sd = _load_session(sid)
    if not sd:
        sd = {
            "id": sid,
            "state": "viewing_dashboard",
            "context": {"current_date": datetime.now(TZ).strftime("%Y-%m-%d"),
                        "selected_entry": None, "filter": None, "pending_data": {}},
            "history": [],
        }
    screen = _handle_dashboard(sd, "start")
    sd["history"].append({"action": "start", "screen": sd["state"], "timestamp": datetime.now(TZ).isoformat()})
    _save_session(sd)
    return output(screen, fmt=format)


@app.command("send")
def send_action(
    action: str = typer.Argument(..., help="callback_data string to send"),
    session: str = typer.Option(..., "--session", help="Session ID"),
    input_text: Optional[str] = typer.Option(None, "--input", help="Text input for free-text screens"),
    format: str = typer.Option("toon", "--format", help="Output format: toon, json, text"),
):
    """Send an action (callback_data) to the current session. Returns next screen."""
    sd = _load_session(session)
    if not sd:
        return output({"text": f"Session '{session}' not found. Start a new session first.",
                        "buttons": [], "session": session, "state": "error",
                        "timestamp": datetime.now(TZ).isoformat()}, fmt=format)

    handler = _resolve_handler(action)
    if handler is None:
        return output({"text": f"Unknown action: '{action}'. No matching handler found.",
                        "buttons": [{"text": "Dashboard", "action": "dashboard"}],
                        "session": sd["id"], "state": sd.get("state", "error"),
                        "timestamp": datetime.now(TZ).isoformat()}, fmt=format)

    try:
        screen = handler(sd, action, input_text)
        sd["history"].append({"action": action, "screen": sd["state"], "timestamp": datetime.now(TZ).isoformat()})
        _save_session(sd)
        return output(screen, fmt=format)
    except Exception as e:
        logger.error("Action handler error: %s", e, exc_info=True)
        return output({"text": f"Error processing action '{action}': {e}",
                        "buttons": [{"text": "Dashboard", "action": "dashboard"}],
                        "session": sd["id"], "state": sd.get("state", "error"),
                        "timestamp": datetime.now(TZ).isoformat()}, fmt=format)


@app.command("status")
def session_status(
    session: str = typer.Option(..., "--session", help="Session ID"),
    format: str = typer.Option("toon", "--format", help="Output format: toon, json, text"),
):
    """Show current session state and history."""
    sd = _load_session(session)
    if not sd:
        return output({"text": f"Session '{session}' not found.", "buttons": [],
                        "session": session, "state": "error",
                        "timestamp": datetime.now(TZ).isoformat()}, fmt=format)

    lines = [
        f"Session: {sd['id']}",
        f"State: {sd['state']}",
        f"Context: {json.dumps(sd.get('context', {}), indent=2)}",
        "",
        f"History ({len(sd.get('history', []))} entries):",
    ]
    for h in sd.get("history", [])[-10:]:
        lines.append(f"  {h['timestamp']}  {h['action']}  ->  {h['screen']}")
    screen = {"text": "\n".join(lines), "buttons": [{"text": "Resume", "action": sd["state"]}],
              "session": sd["id"], "state": sd["state"], "timestamp": datetime.now(TZ).isoformat()}
    return output(screen, fmt=format)


@app.command("reset")
def reset_session(
    session: str = typer.Option(..., "--session", help="Session ID"),
):
    """Clear session state."""
    path = _session_path(session)
    if os.path.exists(path):
        os.remove(path)
        return {"text": f"Session '{session}' reset.", "session": session, "state": "reset",
                "timestamp": datetime.now(TZ).isoformat()}
    return {"text": f"Session '{session}' not found.", "session": session, "state": "error",
            "timestamp": datetime.now(TZ).isoformat()}
