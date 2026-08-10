<!-- T2I HERO SPEC — Subject: a Telegram chat bubble weaving into a Notion database — messages flowing through a small bot node into structured pages. Composition: left chat column, center bot chip, right Notion board. Palette: Telegram sky #229ed9, Notion charcoal #1a1a1a, emerald #10b981 sync path. Style: friendly flat vector, soft glows, no text. 16:9. -->

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![Telegram](https://img.shields.io/badge/Telegram-Bot-0088cc?logo=telegram)
![Notion](https://img.shields.io/badge/Notion-API-000000?logo=notion)
![MCP](https://img.shields.io/badge/MCP-CLI-orange?logo=modelcontextprotocol)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)


> **The LifeOS conversational interface** — a Telegram bot for logging and tracking daily life, backed by a Notion data layer, plus an agent-facing CLI for simulating and driving the same flows headlessly.

LifeOS is a personal-operating-system project: you log **activity, diet, journal, and finances** from your phone (Telegram) and the system responds with dashboards, suggestions, and gap reports built on your trends. The same flows are exposed to AI agents through a `lifeos` CLI so an agent can act as the operator.

## Interfaces

### 1 · Telegram bot

Converse with the bot to log and review:

- **Activity** — entry with suggestions, start/end times, adjacent-before/after expansion, undo
- **Diet** — food logging and tracking
- **Journal** — daily journaling
- **Financial** — expense and money logging

Each domain has a conversation flow with type selection, inline keyboards, and back-to-dashboard navigation.

```
python -m lifeos run                 # start the Telegram bot
```

### 2 · Agent CLI (`python -m lifeos`)

Drive the same service layer as an agent without Telegram:

```bash
python -m lifeos simulate start                # start a simulated session
python -m lifeos simulate send <action> --session <id>
python -m lifeos direct activity --action log --start "09:00" --end "11:00"
python -m lifeos debug notion-consistency      # verify state against Notion
```

```
usage: python -m lifeos [GROUP]
  simulate   replay agent actions against the service layer
  direct     fire a service action directly
  debug      introspection and consistency checks
```

## Features

| Area | What it tracks |
|------|----------------|
| Activity | Logged entries with start/end, adjacent activities, fast-add from gap reports, undo |
| Diet | Food/diet logging across meals |
| Journal | Freeform daily reflection |
| Financial | Expense tracking and money trends |
| Dashboards | Aggregated views from your data |
| Gap reports | Detects uncovered periods/slots to suggest next actions |

## Architecture

```
bot/        Telegram conversation handlers (activity, diet, journal, financial)
services/   domain service layer — activity, diet, journal, financial, dashboard, gap_report
notion/     Notion data layer — client, discovery, models (auto-creates missing DBs)
cli/        typer surface — simulate, direct, debug
config.py   settings + reload (pydantic-settings)
cache.py    diskcache-backed response caching
install.sh  one-shot environment bootstrap
```

- **Notion-backed** — `ensure_database_ids()` discovers or creates databases on startup
- **Cache-aware** — repeated queries hit diskcache rather than re-pinging Notion
- **Simulation harness** — the full agent journey is replayable without a live Telegram session

## Setup

```bash
./install.sh          # bootstraps venv + deps
export TELEGRAM_BOT_TOKEN=...   NOTION_TOKEN=...   # or set in .env
python -m lifeos run
```

Dependencies: `python-telegram-bot`, `notion-client`, `diskcache`, `pydantic`/`pydantic-settings`, `httpx`, `typer`, `rich`.

## Tests

```bash
pytest tests/         # service-level + integration tests incl. gap-report flow
```

## License

MIT.