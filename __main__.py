"""
LifeOS — AI agent interface for Telegram bot simulation.

Usage:
    python -m lifeos simulate start
    python -m lifeos simulate send <action> --session <id>
    python -m lifeos direct activity --action log --start "09:00" --end "11:00"
    python -m lifeos debug notion-consistency
"""

import typer
from cli import simulate, direct, app as debug_app

app = typer.Typer(
    name="lifeos",
    help="LifeOS — AI agent interface for Telegram bot simulation",
    no_args_is_help=True,
)
app.add_typer(simulate.app, name="simulate")
app.add_typer(direct.app, name="direct")
app.add_typer(debug_app, name="debug")

if __name__ == "__main__":
    app()
