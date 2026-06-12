# LifeOS CLI — AI Agent Interface

## Vision

The CLI is **not for humans**. It's a programmatic Telegram simulator for AI agents. The CLI speaks the exact same protocol as the Telegram bot — messages + inline keyboards — but over stdin/stdout. This lets AI agents do autonomous testing, debugging, and evolution of lifeos-bot code.

**Why a Telegram simulator?** The Telegram bot is the source of truth. Its screens, keyboards, and conversation flows are the real interface. Rather than building a parallel CLI that duplicates this logic, we simulate the Telegram bot directly. Every CLI output is a screen with text + buttons. Every CLI input is a callback_data selection. The AI agent navigates the same state machine as a Telegram user.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                Telegram Bot (existing)           │
│  Screen → Message + InlineKeyboardMarkup         │
│  Navigation → callback_data handler              │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│              Service Layer (services/)           │
│  Pure business logic — no Telegram dependency    │
│  log_activity(), detect_gaps(), update_entry()   │
└──────────────────────┬──────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌─────────────────┐     ┌──────────────────────────┐
│ Telegram Bot    │     │ CLI Telegram Simulator   │
│ (existing)      │     │ (new)                    │
│ Message + KB    │     │ Screen + Buttons (TOON)  │
│ via PTB API     │     │ via stdin/stdout          │
└─────────────────┘     └──────────────────────────┘
```

### Key Design Decisions

1. **CLI reuses `bot/formatting.py`** — same HTML rendering, same visual layout
2. **CLI reuses `bot/keyboards.py`** — same inline keyboard structure, same callback_data strings
3. **CLI reuses `services/`** — same business logic, no duplication
4. **CLI outputs TOON format** — AI agents parse cheaply, 30-60% fewer tokens than JSON
5. **CLI maintains session state** — disk-persisted, multi-turn conversations via `--session` flag

## Protocol

### Screen Output (CLI → AI Agent)

Every CLI command returns a **screen** — the exact same text + buttons the Telegram bot would send:

```toon
screen
  text: "📅 Activity Log — Jun 10 (Tue)\n\n12:00-13:00 Work (1h)\n14:00-15:30 Reading (1.5h)\n..."
  buttons
    "➕ Log New" callback_data: "log_new"
    "◀ Prev Day" callback_data: "prev_day"
    "▶ Next Day" callback_data: "next_day"
    "🏠 Dashboard" callback_data: "dashboard"
  session: "cli_abc123"
  state: "viewing_activity_log"
```

### Screen Input (AI Agent → CLI)

The AI agent navigates by sending callback_data selections:

```bash
python -m lifeos simulate --action "log_new" --session "cli_abc123"
```

Or via stdin (for continuous sessions):

```bash
echo '{"action": "log_new", "session": "cli_abc123"}' | python -m lifeos simulate
```

### State Machine

The CLI maintains the same conversation states as the Telegram bot:

```
start → viewing_dashboard
      → viewing_activity_log → viewing_entry_detail → editing_type
                                                    → editing_desc
                                                    → editing_time
                                                    → editing_notes
                                                    → deleting
      → logging_activity → picking_type → entering_desc → confirming
      → viewing_gaps → fast_adding → confirming
      → logging_financial → entering_amount → picking_category → confirming
      → logging_diet → picking_meal → entering_desc → confirming
      → logging_subjective → entering_energy → entering_focus → entering_happiness → confirming
      → logging_relational → entering_person → entering_quality → confirming
      → logging_systemic → entering_bottlenecks → entering_actions → confirming
```

## Implementation

### Phase 1: Service Layer

Extract business logic from handlers into `services/`. This is prerequisite for both the Telegram bot refactoring and the CLI simulator.

| Module | Functions | Source |
|--------|-----------|--------|
| `services/activity.py` | `log_activity()`, `get_entries()`, `update_entry()`, `delete_entry()`, `detect_gaps()`, `compute_suggestions()` | `bot/handlers/activity.py` |
| `services/financial.py` | `log_transaction()`, `get_categories()` | `bot/handlers/financial.py` |
| `services/diet.py` | `log_meal()`, `get_meal_types()` | `bot/handlers/diet.py` |
| `services/journal.py` | `log_subjective()`, `log_relational()`, `log_systemic()` | `bot/handlers/journal.py` |
| `services/dashboard.py` | `get_main_dashboard()`, `get_insights()`, `get_rolling_view()` | `bot/handlers/base.py` |

### Phase 2: Screen Builders

Reuse existing `bot/formatting.py` and `bot/keyboards.py`. The CLI calls the same functions the Telegram handlers call, then renders the output as TOON instead of sending via PTB API.

### Phase 3: CLI Simulator

#### Entry Point: `cli/__main__.py`

```python
import typer
from cli import simulate, debug, direct

app = typer.Typer(
    name="lifeos",
    help="LifeOS — AI agent interface for Telegram bot simulation",
    no_args_is_help=True,
)
app.add_typer(simulate.app, name="simulate")
app.add_typer(debug.app, name="debug")
app.add_typer(direct.app, name="direct")
```

#### Module: `cli/simulate.py` — Telegram Simulator

```python
app = typer.Typer(help="Simulate Telegram bot conversation flow")

@app.command("start")
def start_session(
    session: str = typer.Option(None, help="Session ID (auto-generate if omitted)"),
    format: str = typer.Option("toon", help="Output format: toon, json, text"),
):
    """Start a new CLI session. Returns initial screen (dashboard)."""

@app.command("send")
def send_action(
    action: str = typer.Argument(..., help="callback_data string to send"),
    session: str = typer.Option(..., help="Session ID"),
    input_text: str = typer.Option(None, help="Text input for free-text screens"),
    format: str = typer.Option("toon", help="Output format"),
):
    """Send an action (callback_data) to the current session. Returns next screen."""

@app.command("status")
def session_status(
    session: str = typer.Option(..., help="Session ID"),
    format: str = typer.Option("toon", help="Output format"),
):
    """Show current session state and history."""

@app.command("reset")
def reset_session(
    session: str = typer.Option(..., help="Session ID"),
):
    """Clear session state."""
```

#### Module: `cli/direct.py` — Direct Commands (No State)

For one-shot operations that don't need conversation flow:

```python
app = typer.Typer(help="Direct commands (no session state)")

@app.command("activity")
def activity_direct(
    action: str = typer.Option(..., help="log, view, gaps, search, timeline"),
    type: str = typer.Option(None),
    start: str = typer.Option(None),
    end: str = typer.Option(None),
    desc: str = typer.Option(None),
    page_id: str = typer.Option(None),
    days: int = typer.Option(None),
    format: str = typer.Option("toon", help="Output format"),
    dry_run: bool = typer.Option(False),
):
    """Direct activity operations without conversation flow."""
```

#### Module: `cli/debug.py` — Debugging Commands

```python
app = typer.Typer(help="Debugging and diagnostics")

@app.command("notion-consistency")
def notion_consistency(
    page_id: str = typer.Option(None),
    minutes_ago: int = typer.Option(5),
    format: str = typer.Option("toon"),
):
    """Check Notion eventual consistency status."""

@app.command("timeline-verify")
def timeline_verify(
    page_id: str = typer.Argument(...),
    format: str = typer.Option("toon"),
):
    """Verify entry appears in timeline queries."""

@app.command("cache-status")
def cache_status(format: str = typer.Option("toon")):
    """Show cache hit rate and staleness."""

@app.command("service-health")
def service_health(format: str = typer.Option("toon")):
    """Check all service connections."""

@app.command("audit-telegram-parity")
def audit_parity(format: str = typer.Option("toon")):
    """Cross-reference Telegram features against CLI commands."""

@app.command("state-machine")
def state_machine(
    format: str = typer.Option("toon"),
):
    """Dump all valid states and transitions."""
```

### Phase 4: TOON Output Format

The CLI outputs screens in TOON format — a compact serialization optimized for AI agents:

```toon
# Dashboard Screen
screen: dashboard
text: "🏠 LifeOS Dashboard\n\n📊 48h: 8 entries, 12.5h tracked\n📅 7d: 28 entries, 45h tracked\n..."
buttons:
  1: "📊 Activity Log" → activity_log
  2: "💰 Financial Log" → financial_log
  3: "🍽 Diet Log" → diet_log
  4: "📝 Journal" → journal_menu
  5: "📈 Insights" → insights
session: "cli_abc123"
state: "viewing_dashboard"
timestamp: "2026-06-10T16:17:37+05:30"
```

**TOON benefits for AI agents:**
- 30-60% fewer tokens than JSON
- Buttons are indexed for easy selection: `"1"` to press button 1
- `session` and `state` fields enable multi-turn tracking
- `timestamp` enables timing-dependent debugging

**Parsing by AI agent:**
```python
from toon_format import decode
screen = decode(toon_output)
# screen["buttons"]["1"] → "📊 Activity Log"
# screen["state"] → "viewing_dashboard"
# screen["session"] → "cli_abc123"
```

### Phase 5: Session Persistence

Sessions are persisted to disk at `~/.lifeos/cli_sessions/`:

```
~/.lifeos/cli_sessions/
├── cli_abc123.json    # {state, history, context}
├── cli_def456.json
└── ...
```

Session file structure:
```json
{
  "id": "cli_abc123",
  "state": "viewing_dashboard",
  "context": {
    "current_date": "2026-06-10",
    "selected_entry": "page_123",
    "filter": null
  },
  "history": [
    {"action": "start", "screen": "dashboard", "timestamp": "2026-06-10T16:17:37+05:30"},
    {"action": "activity_log", "screen": "activity_log", "timestamp": "2026-06-10T16:17:45+05:30"}
  ]
}
```

## File Structure

```
lifeos-bot/
├── cli/                          # NEW — AI agent interface
│   ├── __init__.py
│   ├── __main__.py              # Entry point
│   ├── simulate.py              # Telegram simulator (start, send, status, reset)
│   ├── direct.py                # Direct commands (no session state)
│   ├── debug.py                 # Debugging diagnostics
│   └── format.py                # TOON output formatting
├── services/                     # NEW — pure business logic
│   ├── __init__.py
│   ├── activity.py              # Activity CRUD + analytics
│   ├── financial.py             # Financial CRUD
│   ├── diet.py                  # Diet CRUD
│   ├── journal.py               # Journal CRUD
│   └── dashboard.py             # Dashboard aggregation
├── bot/                          # EXISTING — refactored to use services/
│   ├── handlers/
│   ├── formatting.py
│   ├── keyboards.py
│   └── main.py
├── notion/                       # EXISTING — unchanged
├── __main__.py                   # NEW — entry point
└── pyproject.toml
```

## Implementation Order

| Step | Task | Est. Lines | Dependencies |
|------|------|-----------|--------------|
| 1 | Create `services/` package | 5 | None |
| 2 | Extract `services/financial.py` | 60 | None |
| 3 | Extract `services/diet.py` | 60 | None |
| 4 | Extract `services/journal.py` | 100 | None |
| 5 | Extract `services/activity.py` | 250 | None |
| 6 | Extract `services/dashboard.py` | 80 | services/activity |
| 7 | Create `cli/` package | 5 | None |
| 8 | Create `cli/format.py` (TOON output) | 80 | None |
| 9 | Create `cli/simulate.py` (Telegram simulator) | 200 | services/*, cli/format |
| 10 | Create `cli/direct.py` (one-shot commands) | 150 | services/*, cli/format |
| 11 | Create `cli/debug.py` (debugging commands) | 120 | services/*, cache |
| 12 | Create `__main__.py` entry point | 10 | cli/* |
| 13 | Update `pyproject.toml` | 2 | None |
| 14 | Refactor `bot/handlers/financial.py` | 30 | services/financial |
| 15 | Refactor `bot/handlers/diet.py` | 30 | services/diet |
| 16 | Refactor `bot/handlers/journal.py` | 40 | services/journal |
| 17 | Refactor `bot/handlers/activity.py` | 80 | services/activity |
| 18 | Refactor `bot/handlers/base.py` | 30 | services/dashboard |
| 19 | Integration test | — | All above |

## Usage Examples

### AI Agent Workflow — Session-Based

```bash
# Start session → get dashboard screen
SCREEN=$(python -m lifeos simulate start)
SESSION=$(echo "$SCREEN" | python -c "from toon_format import decode; print(decode(sys.stdin.read())['session'])")

# Navigate to activity log
SCREEN=$(python -m lifeos simulate send "activity_log" --session "$SESSION")

# View today's entries
SCREEN=$(python -m lifeos simulate send "view_today" --session "$SESSION")

# Log new activity
SCREEN=$(python -m lifeos simulate send "log_new" --session "$SESSION")
SCREEN=$(python -m lifeos simulate send "pick_type:Work" --session "$SESSION" --input-text "2026-06-10 09:00")
SCREEN=$(python -m lifeos simulate send "pick_time:09:00-11:00" --session "$SESSION")
SCREEN=$(python -m lifeos simulate send "confirm" --session "$SESSION")
```

### AI Agent Workflow — Direct Commands

```bash
# One-shot operations
python -m lifeos direct activity --action log --type "Work" --start "2026-06-10 09:00" --end "2026-06-10 11:00"
python -m lifeos direct activity --action gaps --days 7
python -m lifeos direct activity --action timeline --days 3
```

### Debugging Workflow

```bash
# Check Notion consistency
python -m lifeos debug notion-consistency --page-id "page_123"

# Verify entry appears in timeline
python -m lifeos debug timeline-verify "page_123"

# Check cache status
python -m lifeos debug cache-status

# Audit Telegram feature parity
python -m lifeos debug audit-telegram-parity

# Dump state machine
python -m lifeos debug state-machine
```

## Telegram Feature Parity

| Telegram Screen | CLI Screen Builder | Callback Data |
|----------------|-------------------|---------------|
| Main Dashboard | `formatting.build_main_dashboard()` | `dashboard` |
| Activity Log | `formatting.build_activity_log()` | `activity_log` |
| Entry Detail | `formatting.build_entry_detail()` | `entry_detail:{page_id}` |
| Time Picker | `formatting.build_time_picker()` | `pick_time:{time}` |
| Type Picker | `formatting.build_type_picker()` | `pick_type:{type}` |
| Description Input | `formatting.build_desc_input()` | `enter_desc:{text}` |
| Gap Report | `formatting.build_gap_report()` | `gaps` |
| Fast Add | `formatting.build_fast_add()` | `fast_add:{gap_id}` |
| Financial Log | `formatting.build_financial_log()` | `financial_log` |
| Diet Log | `formatting.build_diet_log()` | `diet_log` |
| Journal Menu | `formatting.build_journal_menu()` | `journal_menu` |
| Insights | `formatting.build_insights()` | `insights` |

## Dependencies

```
# Existing (unchanged)
python-telegram-bot>=20.0
notion-client

# New (CLI)
typer>=0.9.0
rich>=13.0.0
toon-format>=0.1.0
```

## Integration with AI Agents

### Direct Python Import (Preferred)

```python
from services.activity import log_activity, get_entries, detect_gaps
from services.dashboard import get_main_dashboard

# AI agent can call services directly
dashboard = await get_main_dashboard()
gaps = await detect_gaps(min_hours=4)
if gaps:
    await log_activity(
        start=gaps[0].start_dt,
        end=gaps[0].end_dt,
        activity_type="Work",
        note="Auto-filled gap"
    )
```

### CLI Subprocess (Fallback)

```bash
# For AI agents that can't import Python directly
SCREEN=$(python -m lifeos simulate start)
# Parse TOON output, navigate, act
```

### MCP Integration (Future)

Wrap each service function as an MCP tool — the service layer makes this trivial:

```python
# mcp/tools.py
from services.activity import log_activity, get_entries, detect_gaps

@mcp.tool()
async def log_activity(start: str, end: str, type: str, desc: str = "") -> str:
    """Log an activity entry."""
    entry = await log_activity(start, end, type, desc)
    return toon_encode(entry)
```
