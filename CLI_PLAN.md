# LifeOS CLI Implementation Plan

## Architecture Overview

The goal is to extract business logic from Telegram-coupled handlers into a **pure service layer**, then build a **typer CLI** on top of it. This enables both human CLI usage and AI agent automation.

```
┌─────────────────┐     ┌─────────────────┐
│  Telegram Bot    │     │  typer CLI       │
│  (existing)      │     │  (new)           │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────┐
│           Service Layer                 │
│  (services/) — pure business logic      │
│  No Telegram or CLI dependencies        │
└────────────────────┬────────────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  notion/client  │     │  bot/insights   │
│  (existing)     │     │  (existing)     │
└─────────────────┘     └─────────────────┘
```

---

## Phase 1: Service Layer Extraction

### New module: `services/__init__.py`

Empty init file.

### New module: `services/activity.py`

**Extract from `bot/handlers/activity.py`:**

| Current Location | Service Function | Description |
|---|---|---|
| `_save_activity` (line ~790) | `log_activity(start, end, type, desc, note)` → `ActivityEntry` | Creates activity entry, returns saved entry with ID |
| `_compute_time_suggestions` (line ~329) | `compute_time_suggestions(entries_48h, now, last_saved_end)` → `List[TimeSuggestion]` | Gap-based time suggestions |
| Dashboard rendering logic (line ~69) | `get_dashboard_data()` → `DashboardData` | Stats, categories, predictions |
| `daily_view_callback` (line ~555) | `get_entries_for_window(start, end)` → `List[ActivityEntry]` | Query entries for a time window |
| `show_entry_detail` (line ~620) | `get_entry_detail(page_id)` → `ActivityEntry` | Fetch single entry |
| `edit_type_chosen` (line ~695) | `update_entry_type(page_id, new_type)` → `ActivityEntry` | Update entry type |
| `edit_desc_entered` (line ~735) | `update_entry_desc(page_id, new_desc)` → `ActivityEntry` | Update entry description |
| `edit_end_minute_chosen` (line ~810) | `update_entry_times(page_id, new_start, new_end)` → `ActivityEntry` | Update entry times |
| `edit_notes_entered` (line ~870) | `update_entry_notes(page_id, new_notes)` → `ActivityEntry` | Update entry notes |
| `delete_entry_confirm` (line ~895) | `delete_entry(page_id)` → `bool` | Delete/archive entry |
| `check_activity_gaps` (line ~1050) | `detect_gaps(min_hours=4)` → `List[Gap]` | Find gaps in entries |
| `add_adjacent_before/after` logic | `compute_adjacent_suggestions(entry, direction)` → `List[TimeSuggestion]` | Adjacent entry suggestions |

**Key data structures (defined in `services/activity.py`):**

```python
@dataclass
class ActivityEntry:
    id: str
    page_id: str
    title: str
    activity_type: str
    activity_notes: str
    start: datetime
    end: datetime
    duration_hrs: float

@dataclass
class TimeSuggestion:
    label: str
    start: datetime
    end: datetime
    start_only: bool = False

@dataclass
class DashboardData:
    entries_48h: int
    hrs_48h: float
    entries_7d: int
    hrs_7d: float
    entries_30d: int
    hrs_30d: float
    category_breakdown: List[Tuple[str, float]]
    insights: str  # rendered HTML/text
    predictions: List[Tuple[str, float, str]]
    suggestions: List[str]
    recent_entries: List[ActivityEntry]

@dataclass
class Gap:
    date: str
    start: str
    end: str
    hours: float
    start_dt: datetime
    end_dt: datetime
```

### New module: `services/financial.py`

**Extract from `bot/handlers/financial.py`:**

| Current Location | Service Function | Description |
|---|---|---|
| `_save_financial` (line ~98) | `log_transaction(type, amount, category, note)` → `dict` | Creates financial entry |
| `amount_entered` (line ~41) | `get_categories()` → `List[str]` | Fetch available categories |

### New module: `services/diet.py`

**Extract from `bot/handlers/diet.py`:**

| Current Location | Service Function | Description |
|---|---|---|
| `_save_diet` (line ~110) | `log_meal(meal_type, description, calories, note)` → `dict` | Creates diet entry |
| `start_diet_flow` (line ~18) | `get_meal_types()` → `List[str]` | Fetch available meal types |

### New module: `services/journal.py`

**Extract from `bot/handlers/journal.py`:**

| Current Location | Service Function | Description |
|---|---|---|
| `_save_subjective` (line ~67) | `log_subjective(energy, focus, happiness, gratitude)` → `dict` | Creates subjective journal |
| `_save_relational` (line ~153) | `log_relational(person, quality, insights)` → `dict` | Creates relational journal |
| `_save_systemic` (line ~209) | `log_systemic(bottlenecks, actions)` → `dict` | Creates systemic journal |

### New module: `services/dashboard.py`

**Extract from `bot/handlers/base.py` and `bot/formatting.py`:**

| Current Location | Service Function | Description |
|---|---|---|
| `_build_main_dashboard` (line ~20) | `get_main_dashboard()` → `DashboardSummary` | Main hub data |
| — | `get_insights(entries)` → `InsightsData` | Pattern analysis wrapper |
| — | `get_rolling_view(start, end)` → `RollingViewData` | Rolling view data |

**Key data structures:**

```python
@dataclass
class DashboardSummary:
    entries_48h: int
    hrs_48h: float
    untracked_hrs: float
    tracked_pct: float
    last_entry: Optional[ActivityEntry]
    untracked_since: Optional[str]
    top_categories: List[Tuple[str, float]]

@dataclass
class InsightsData:
    most_consistent: Optional[Tuple[str, float]]  # (type, avg_hour)
    avg_sessions: List[Tuple[str, float]]  # (type, avg_duration)
    gap_pattern: Optional[dict]
    dow_peak: Optional[str]
    consistency: dict
    predictions: List[Tuple[str, float, str]]
```

---

## Phase 2: CLI Implementation

### New module: `cli/__init__.py`

Empty init.

### New module: `cli/__main__.py`

```python
import typer
from cli import activity, financial, diet, journal, dashboard, discovery

app = typer.Typer(
    name="lifeos",
    help="LifeOS — manage your Notion life-tracking databases from the CLI",
    no_args_is_help=True,
)
app.add_typer(activity.app, name="activity")
app.add_typer(financial.app, name="financial")
app.add_typer(diet.app, name="diet")
app.add_typer(journal.app, name="journal")
app.add_typer(dashboard.app, name="dashboard")
app.add_typer(discovery.app, name="discovery")

if __name__ == "__main__":
    app()
```

### New module: `cli/activity.py`

```python
app = typer.Typer(help="Activity log management")

@app.command()
def log(
    type: str = typer.Option(..., help="Activity type"),
    start: str = typer.Option(..., help="Start time (YYYY-MM-DD HH:MM)"),
    end: str = typer.Option(..., help="End time (YYYY-MM-DD HH:MM)"),
    desc: str = typer.Option("", help="Description"),
    note: str = typer.Option("", help="Notes"),
):
    """Log a new activity entry."""
    # Parse times, call services.log_activity()

@app.command()
def dashboard():
    """Show activity dashboard with stats and insights."""
    # Call services.get_dashboard_data()

@app.command()
def view(
    date: str = typer.Option("today", help="Date or 'today'/'yesterday'"),
):
    """View entries for a specific date/window."""
    # Call services.get_entries_for_window()

@app.command()
def edit(
    page_id: str = typer.Argument(..., help="Entry page ID"),
    type: str = typer.Option(None, help="New activity type"),
    desc: str = typer.Option(None, help="New description"),
    start: str = typer.Option(None, help="New start time"),
    end: str = typer.Option(None, help="New end time"),
    note: str = typer.Option(None, help="New notes"),
):
    """Edit an existing activity entry."""
    # Call appropriate service functions

@app.command()
def delete(page_id: str = typer.Argument(...)):
    """Delete/archive an activity entry."""
    # Call services.delete_entry()

@app.command()
def gaps(days: int = typer.Option(7, help="Look back N days")):
    """Show gap report."""
    # Call services.detect_gaps()

@app.command()
def types():
    """List available activity types."""
    # Call notion_manager.get_activity_types()

@app.command()
def search(query: str = typer.Argument(...)):
    """Search entries by type, notes, or date range."""
    # Implemented via query_activity_entries with filters
```

### New module: `cli/financial.py`

```python
app = typer.Typer(help="Financial log management")

@app.command()
def log(
    type: str = typer.Option(..., help="Expense or Income"),
    amount: float = typer.Option(..., help="Amount"),
    category: str = typer.Option(..., help="Category"),
    note: str = typer.Option("", help="Notes"),
):
    """Log a financial transaction."""

@app.command()
def categories():
    """List available categories."""
```

### New module: `cli/diet.py`

```python
app = typer.Typer(help="Diet log management")

@app.command()
def log(
    meal: str = typer.Option(..., help="Meal type"),
    description: str = typer.Option(..., help="What you ate"),
    calories: int = typer.Option(None, help="Calories (optional)"),
    note: str = typer.Option("", help="Notes"),
):
    """Log a meal."""

@app.command()
def meals():
    """List available meal types."""
```

### New module: `cli/journal.py`

```python
app = typer.Typer(help="Journal management")

@app.command()
def subjective(
    energy: int = typer.Option(None, help="Energy 1-10"),
    focus: int = typer.Option(None, help="Focus 1-10"),
    happiness: int = typer.Option(None, help="Happiness 1-10"),
    gratitude: str = typer.Option("", help="Gratitude text"),
):
    """Log subjective journal entry."""

@app.command()
def relational(
    person: str = typer.Option(..., help="Person name"),
    quality: int = typer.Option(None, help="Connection quality 1-10"),
    insights: str = typer.Option("", help="Insights"),
):
    """Log relational journal entry."""

@app.command()
def systemic(
    bottlenecks: str = typer.Option(..., help="Current bottlenecks"),
    actions: str = typer.Option(..., help="Actionable changes"),
):
    """Log systemic journal entry."""
```

### New module: `cli/dashboard.py`

```python
app = typer.Typer(help="Dashboard and insights")

@app.command()
def main():
    """Show main LifeOS dashboard."""

@app.command()
def insights(days: int = typer.Option(30)):
    """Show pattern analysis and predictions."""
```

### New module: `cli/discovery.py`

```python
app = typer.Typer(help="Database discovery and management")

@app.command()
def discover():
    """Discover Notion databases and update .env."""

@app.command()
def status():
    """Show current database IDs and connection status."""
```

---

## Phase 3: Refactor Telegram Handlers

After the service layer is built and tested, refactor each handler to call service functions instead of inline logic.

### Refactoring pattern:

**Before:**
```python
# bot/handlers/financial.py
async def _save_financial(update, context):
    tx_type = context.user_data.get("fin_type")
    amount = context.user_data.get("fin_amount")
    category = context.user_data.get("fin_category")
    note = context.user_data.get("fin_note")
    # ... build Notion payload inline ...
    properties = {"Name": NB.title(...), "Type": NB.select(...), ...}
    await notion_manager.create_page(settings.DATABASE_ID_FINANCIAL_LOG, properties)
    # ... format Telegram response inline ...
```

**After:**
```python
# bot/handlers/financial.py
from services.financial import log_transaction

async def _save_financial(update, context):
    tx_type = context.user_data.get("fin_type")
    amount = context.user_data.get("fin_amount")
    category = context.user_data.get("fin_category")
    note = context.user_data.get("fin_note")
    result = await log_transaction(tx_type, amount, category, note)
    # ... format Telegram response only ...
```

### Files to refactor (in order):
1. `bot/handlers/financial.py` — simplest, good proof of concept
2. `bot/handlers/diet.py` — similar structure
3. `bot/handlers/journal.py` — three journal types
4. `bot/handlers/activity.py` — most complex, do last
5. `bot/handlers/base.py` — dashboard rendering

---

## Phase 4: Add `__main__.py` Entry Point

### New file: `__main__.py` (project root)

```python
#!/usr/bin/env python3
"""Allow running as `python -m lifeos-bot` or `lifeos`."""
from cli.__main__ import app
app()
```

### Update `pyproject.toml` or create one:

```toml
[project.scripts]
lifeos = "cli.__main__:app"
```

Or if keeping `requirements.txt`-only:

```
# Add to requirements.txt
typer>=0.9.0
rich>=13.0.0  # for nice terminal output
```

---

## Phase 5: Output Formatting

### New module: `cli/formatting.py`

Plain-text formatting for CLI output (as opposed to `bot/formatting.py` which uses Telegram HTML).

```python
# Uses rich for beautiful terminal output
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console()

def print_dashboard(data: DashboardData): ...
def print_entries(entries: List[ActivityEntry]): ...
def print_gap_report(gaps: List[Gap]): ...
def print_insights(insights: InsightsData): ...
def print_entry_detail(entry: ActivityEntry): ...
```

---

## File Structure (Final)

```
lifeos-bot/
├── cli/                          # NEW — CLI layer
│   ├── __init__.py
│   ├── __main__.py              # typer app registration
│   ├── activity.py              # activity commands
│   ├── financial.py             # financial commands
│   ├── diet.py                  # diet commands
│   ├── journal.py               # journal commands
│   ├── dashboard.py             # dashboard/insights commands
│   ├── discovery.py             # DB discovery commands
│   └── formatting.py            # rich terminal output
├── services/                     # NEW — pure business logic
│   ├── __init__.py
│   ├── activity.py              # activity CRUD + analytics
│   ├── financial.py             # financial CRUD
│   ├── diet.py                  # diet CRUD
│   ├── journal.py               # journal CRUD (all 3 types)
│   └── dashboard.py             # dashboard data aggregation
├── notion/                       # EXISTING — unchanged
│   ├── client.py
│   ├── models.py
│   └── discovery.py
├── bot/                          # EXISTING — refactored to use services/
│   ├── handlers/
│   │   ├── activity.py
│   │   ├── financial.py
│   │   ├── diet.py
│   │   ├── journal.py
│   │   └── base.py
│   ├── formatting.py
│   ├── keyboards.py
│   ├── insights.py
│   └── main.py
├── __main__.py                   # NEW — entry point
├── config.py                     # EXISTING — unchanged
├── cache.py                      # EXISTING — unchanged
├── run.py                        # EXISTING — unchanged
└── requirements.txt              # UPDATED — add typer, rich
```

---

## Implementation Order

| Step | Task | Est. Lines | Dependencies |
|------|------|-----------|--------------|
| 1 | Create `services/` package with `__init__.py` | 5 | None |
| 2 | Extract `services/financial.py` (simplest handler) | 60 | None |
| 3 | Extract `services/diet.py` | 60 | None |
| 4 | Extract `services/journal.py` (3 types) | 100 | None |
| 5 | Extract `services/activity.py` (most complex) | 250 | None |
| 6 | Extract `services/dashboard.py` | 80 | services/activity |
| 7 | Create `cli/` package with `__init__.py` | 5 | None |
| 8 | Create `cli/__main__.py` (typer app) | 20 | None |
| 9 | Create `cli/activity.py` commands | 120 | services/activity |
| 10 | Create `cli/financial.py` commands | 40 | services/financial |
| 11 | Create `cli/diet.py` commands | 40 | services/diet |
| 12 | Create `cli/journal.py` commands | 60 | services/journal |
| 13 | Create `cli/dashboard.py` commands | 40 | services/dashboard |
| 14 | Create `cli/discovery.py` commands | 30 | notion/discovery |
| 15 | Create `cli/formatting.py` (rich output) | 100 | None |
| 16 | Create `__main__.py` entry point | 10 | cli/__main__ |
| 17 | Update `requirements.txt` | 2 | None |
| 18 | Refactor `bot/handlers/financial.py` to use services | 30 | services/financial |
| 19 | Refactor `bot/handlers/diet.py` to use services | 30 | services/diet |
| 20 | Refactor `bot/handlers/journal.py` to use services | 40 | services/journal |
| 21 | Refactor `bot/handlers/activity.py` to use services | 80 | services/activity |
| 22 | Refactor `bot/handlers/base.py` to use services | 30 | services/dashboard |
| 23 | Integration test — CLI + bot both work | — | All above |

---

## CLI Usage Examples

```bash
# Activity
python -m lifeos-bot activity log --type "Work" --start "2026-06-10 09:00" --end "2026-06-10 11:00" --desc "Coding session" --note "Built CLI"
python -m lifeos-bot activity dashboard
python -m lifeos-bot activity view --date today
python -m lifeos-bot activity gaps --days 7
python -m lifeos-bot activity types
python -m lifeos-bot activity edit <page_id> --type "Study"
python -m lifeos-bot activity delete <page_id>

# Financial
python -m lifeos-bot financial log --type Expense --amount 42.50 --category Food --note "Lunch"
python -m lifeos-bot financial categories

# Diet
python -m lifeos-bot diet log --meal Lunch --description "Rice and curry" --calories 650
python -m lifeos-bot diet meals

# Journals
python -m lifeos-bot journal subjective --energy 8 --focus 7 --happiness 9 --gratitude "Good progress"
python -m lifeos-bot journal relational --person "Alice" --quality 8 --insights "Great conversation"
python -m lifeos-bot journal systemic --bottlenecks "Too many meetings" --actions "Block focus time"

# Dashboard
python -m lifeos-bot dashboard main
python -m lifeos-bot dashboard insights --days 30

# Discovery
python -m lifeos-bot discovery discover
python -m lifeos-bot discovery status
```

---

## AI Agent Integration Path

Once the service layer exists, AI agents can call it directly:

```python
# Direct service calls (no CLI needed)
from services.activity import log_activity, get_dashboard_data, detect_gaps
from services.financial import log_transaction
from services.diet import log_meal
from services.journal import log_subjective, log_relational, log_systemic

# Example agent workflow:
dashboard = await get_dashboard_data()
gaps = await detect_gaps(min_hours=4)
if gaps:
    await log_activity(
        start=gaps[0].start_dt,
        end=gaps[0].end_dt,
        activity_type="Work",
        note="Auto-filled gap"
    )
```

For MCP (Model Context Protocol) integration later, wrap each service function as an MCP tool — the service layer makes this trivial.
