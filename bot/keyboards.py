# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/keyboards.py

from typing import List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_grid_keyboard(options: List[str], callback_prefix: str, row_width: int = 2) -> InlineKeyboardMarkup:
    """Converts a flat list of option strings into a responsive inline button grid."""
    keyboard: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for opt in options:
        row.append(InlineKeyboardButton(text=opt, callback_data=f"{callback_prefix}:{opt}"))
        if len(row) == row_width:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


def build_hour_keyboard(prefix: str, selected_hour: Optional[int] = None, back_callback: str = "act_back_dash") -> InlineKeyboardMarkup:
    """
    Hour picker: 24 buttons (00-23), 6 per row = 4 rows.
    Callback data: prefix:HH (e.g. s_hr:08)
    """
    keyboard: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for hour in range(24):
        label = f"{hour:02d}"
        if hour == selected_hour:
            label = f"[{label}]"
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{hour:02d}"))
        if len(row) == 6:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="Back to Activity", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)


def build_minute_keyboard(prefix: str, hour: int, selected_minute: Optional[int] = None) -> InlineKeyboardMarkup:
    """
    Minute picker: 4 buttons (00, 15, 30, 45) for a given hour.
    Callback data: prefix:HHMM (e.g. s_min:0830)
    """
    keyboard: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for minute in [0, 15, 30, 45]:
        label = f"{hour:02d}:{minute:02d}"
        if minute == selected_minute:
            label = f"[{label}]"
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{hour:02d}{minute:02d}"))
    keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="Back", callback_data=f"{prefix}_back")])
    return InlineKeyboardMarkup(keyboard)


def build_suggestions_keyboard(suggestions: List[dict], prefix: str) -> InlineKeyboardMarkup:
    """
    Smart time suggestions based on gaps.
    suggestions: list of {label, start_hhmm, end_hhmm}
    Callback data: prefix:START_HHMM-END_HHMM
    """
    keyboard: List[List[InlineKeyboardButton]] = []
    for s in suggestions:
        keyboard.append([InlineKeyboardButton(
            text=s["label"],
            callback_data=f"{prefix}:{s['start_hhmm']}-{s['end_hhmm']}",
        )])
    keyboard.append([InlineKeyboardButton(text="Custom time...", callback_data=f"{prefix}:custom")])
    keyboard.append([InlineKeyboardButton(text="Back to Activity", callback_data="act_back_dash")])
    return InlineKeyboardMarkup(keyboard)


def build_number_keyboard(callback_prefix: str, start: int = 1, end: int = 10, row_width: int = 5) -> InlineKeyboardMarkup:
    """Builds a numeric rating grid (e.g. 1-10) for journal scales."""
    keyboard: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for n in range(start, end + 1):
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"{callback_prefix}:{n}"))
        if len(row) == row_width:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="Skip", callback_data=f"{callback_prefix}:skip")])
    return InlineKeyboardMarkup(keyboard)


def build_main_menu() -> InlineKeyboardMarkup:
    """Top-level hub."""
    keyboard = [
        [
            InlineKeyboardButton(text="Activity", callback_data="sub:activity"),
            InlineKeyboardButton(text="Financial", callback_data="sub:financial"),
        ],
        [
            InlineKeyboardButton(text="Diet", callback_data="sub:diet"),
            InlineKeyboardButton(text="Journal", callback_data="sub:journal"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_activity_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Activity dashboard with New Entry, Today, Yesterday, Gaps, Back."""
    keyboard = [
        [InlineKeyboardButton(text="+ New Entry", callback_data="menu:activity")],
        [
            InlineKeyboardButton(text="Today", callback_data="act_view:today"),
            InlineKeyboardButton(text="Yesterday", callback_data="act_view:yesterday"),
        ],
        [InlineKeyboardButton(text="Gaps (7d)", callback_data="act_gaps:7d")],
        [InlineKeyboardButton(text="Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_activity_dashboard_with_entries_keyboard(
    entry_page_ids: List[str],
    entry_labels: List[str],
    gap_buttons: List[dict],
) -> InlineKeyboardMarkup:
    """
    Dashboard keyboard with last 24h entries as CRUD buttons + gap-fill buttons.
    gap_buttons: list of {start_hhmm, end_hhmm, label}
    """
    keyboard: List[List[InlineKeyboardButton]] = []

    # Gap-fill buttons first
    for g in gap_buttons:
        keyboard.append([InlineKeyboardButton(
            text=g["label"],
            callback_data=f"act_gap:{g['start_hhmm']}-{g['end_hhmm']}",
        )])

    # Entry buttons (tap to view/edit)
    for page_id, label in zip(entry_page_ids, entry_labels):
        keyboard.append([InlineKeyboardButton(
            text=label,
            callback_data=f"act_entry:{page_id[:36]}",
        )])

    # Standard dashboard buttons
    keyboard.append([InlineKeyboardButton(text="+ New Entry", callback_data="menu:activity")])
    keyboard.append([
        InlineKeyboardButton(text="Today", callback_data="act_view:today"),
        InlineKeyboardButton(text="Yesterday", callback_data="act_view:yesterday"),
    ])
    keyboard.append([InlineKeyboardButton(text="Gaps (7d)", callback_data="act_gaps:7d")])
    keyboard.append([InlineKeyboardButton(text="Back", callback_data="menu:main")])
    return InlineKeyboardMarkup(keyboard)


def build_rolling_view_keyboard(
    back_24h_iso: str, fwd_24h_iso: str,
    w_back_iso: str, w_fwd_iso: str,
    m_back_iso: str, m_fwd_iso: str,
) -> InlineKeyboardMarkup:
    """Rolling 24h view navigation with ±24h, ±7d, ±30d buttons."""
    keyboard: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="<<30d", callback_data=f"act_view:{m_back_iso}"),
            InlineKeyboardButton(text="<7d", callback_data=f"act_view:{w_back_iso}"),
            InlineKeyboardButton(text="<24h", callback_data=f"act_view:{back_24h_iso}"),
        ],
        [
            InlineKeyboardButton(text="Now", callback_data="act_view:today"),
        ],
        [
            InlineKeyboardButton(text="24h>", callback_data=f"act_view:{fwd_24h_iso}"),
            InlineKeyboardButton(text="7d>", callback_data=f"act_view:{w_fwd_iso}"),
            InlineKeyboardButton(text="30d>>", callback_data=f"act_view:{m_fwd_iso}"),
        ],
        [
            InlineKeyboardButton(text="+ New Entry", callback_data="menu:activity"),
            InlineKeyboardButton(text="Back", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_entry_detail_keyboard(page_id: str) -> InlineKeyboardMarkup:
    """Edit/delete/adjacent-add options for a single entry."""
    keyboard = [
        [
            InlineKeyboardButton(text="Edit Type", callback_data=f"edt_type:{page_id[:36]}"),
            InlineKeyboardButton(text="Edit Times", callback_data=f"edt_time:{page_id[:36]}"),
        ],
        [
            InlineKeyboardButton(text="Edit Desc", callback_data=f"edt_desc:{page_id[:36]}"),
        ],
        [
            InlineKeyboardButton(text="Add Before", callback_data=f"adj_before:{page_id[:36]}"),
            InlineKeyboardButton(text="Add After", callback_data=f"adj_after:{page_id[:36]}"),
        ],
        [
            InlineKeyboardButton(text="Delete", callback_data=f"edt_del:{page_id[:36]}"),
        ],
        [
            InlineKeyboardButton(text="Back to Day", callback_data="act_view:today"),
            InlineKeyboardButton(text="Back to Activity", callback_data="sub:activity"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_confirm_keyboard(confirm_callback: str, cancel_callback: str = "act_view:today") -> InlineKeyboardMarkup:
    """Yes/No confirmation."""
    keyboard = [
        [
            InlineKeyboardButton(text="Yes", callback_data=confirm_callback),
            InlineKeyboardButton(text="No", callback_data=cancel_callback),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_financial_submenu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="+ Log Transaction", callback_data="menu:financial")],
        [InlineKeyboardButton(text="Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_diet_submenu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="+ Log Meal", callback_data="menu:diet")],
        [InlineKeyboardButton(text="Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_journal_submenu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="Subjective Journal", callback_data="menu:subjective_journal")],
        [InlineKeyboardButton(text="Relational Journal", callback_data="menu:relational_journal")],
        [InlineKeyboardButton(text="Systemic Journal", callback_data="menu:systemic_journal")],
        [InlineKeyboardButton(text="Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_edit_time_offset_keyboard(page_id: str) -> InlineKeyboardMarkup:
    """
    Time offset shortcut buttons for editing entry start/end times.
    6 durations (15/30/45/60/90/120 min) x add/subtract for start and end = 24 buttons.
    """
    offsets = [15, 30, 45, 60, 75, 90, 105, 120]
    keyboard: List[List[InlineKeyboardButton]] = []

    def _add_offset_rows(target: str):
        """Add 2 rows of subtract (6 buttons, 3 per row) then 2 rows of add."""
        keyboard.append([InlineKeyboardButton(text=f"── {target.upper()} ──", callback_data="noop")])
        for sign_char in ("-", "+"):
            row: List[InlineKeyboardButton] = []
            for mins in offsets:
                row.append(InlineKeyboardButton(
                    text=f"{sign_char}{mins}",
                    callback_data=f"edt_offset:{target}:{sign_char}{mins}",
                ))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

    _add_offset_rows("start")
    _add_offset_rows("end")

    keyboard.append([
        InlineKeyboardButton(text="Custom Start", callback_data="edt_start_custom"),
        InlineKeyboardButton(text="Custom End", callback_data="edt_end_custom"),
    ])
    keyboard.append([InlineKeyboardButton(text="Back to Entry", callback_data=f"act_entry:{page_id[:36]}")])
    return InlineKeyboardMarkup(keyboard)


def build_back_button(callback: str = "menu:main") -> InlineKeyboardMarkup:
    """Single back button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data=callback)]])


def financial_entry_detail_keyboard(page_id: str) -> InlineKeyboardMarkup:
    """Edit/delete options for a single financial entry."""
    keyboard = [
        [
            InlineKeyboardButton(text="💰 Amount", callback_data=f"fin_edit_amount:{page_id[:36]}"),
            InlineKeyboardButton(text="📂 Category", callback_data=f"fin_edit_category:{page_id[:36]}"),
            InlineKeyboardButton(text="🏷️ Type", callback_data=f"fin_edit_type:{page_id[:36]}"),
        ],
        [
            InlineKeyboardButton(text="📅 Date", callback_data=f"fin_edit_date:{page_id[:36]}"),
            InlineKeyboardButton(text="📝 Notes", callback_data=f"fin_edit_notes:{page_id[:36]}"),
            InlineKeyboardButton(text="🗑 Delete", callback_data=f"fin_delete:{page_id[:36]}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="fin_log"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def financial_edit_field_keyboard(page_id: str, field: str) -> InlineKeyboardMarkup:
    """Field-specific edit keyboard for financial entries."""
    if field == "type":
        keyboard = [
            [InlineKeyboardButton(text="💵 Income", callback_data=f"fin_set_type:{page_id[:36]}:Income")],
            [InlineKeyboardButton(text="💸 Expense", callback_data=f"fin_set_type:{page_id[:36]}:Expense")],
            [InlineKeyboardButton(text="💰 Savings", callback_data=f"fin_set_type:{page_id[:36]}:Savings")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"fin_cancel_edit:{page_id[:36]}")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"fin_cancel_edit:{page_id[:36]}")],
        ]
    return InlineKeyboardMarkup(keyboard)


def diet_entry_detail_keyboard(page_id: str) -> InlineKeyboardMarkup:
    """Edit/delete options for a single diet entry."""
    keyboard = [
        [
            InlineKeyboardButton(text="✏️ Meal Type", callback_data=f"diet_edit_type:{page_id}"),
            InlineKeyboardButton(text="📝 Description", callback_data=f"diet_edit_desc:{page_id}"),
            InlineKeyboardButton(text="🔢 Calories", callback_data=f"diet_edit_calories:{page_id}"),
        ],
        [
            InlineKeyboardButton(text="📅 Date", callback_data=f"diet_edit_date:{page_id}"),
            InlineKeyboardButton(text="🗑 Delete", callback_data=f"diet_delete:{page_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Back", callback_data="diet_log"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def diet_edit_field_keyboard(page_id: str, field: str) -> InlineKeyboardMarkup:
    """Field-specific edit keyboard for diet entries."""
    keyboard: List[List[InlineKeyboardButton]] = []
    if field == "meal_type":
        meals = ["🍳 Breakfast", "🥗 Lunch", "🍽️ Dinner", "🍿 Snack"]
        for meal in meals:
            clean_name = meal.split(" ", 1)[1]
            keyboard.append([InlineKeyboardButton(
                text=meal,
                callback_data=f"diet_set_type:{page_id}:{clean_name}",
            )])
    keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data=f"diet_cancel_edit:{page_id}")])
    return InlineKeyboardMarkup(keyboard)
