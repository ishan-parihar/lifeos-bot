"""
LifeOS CLI output formatting.

Dispatches between three output formats:
- toon: Compact serialization optimized for AI agents (30-60% fewer tokens than JSON)
- rich: Pretty terminal output using the ``rich`` library
- text: Plain text, minimal formatting, HTML tags stripped
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text as RichText

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

try:
    import toon_format as toon_lib

    _HAS_TOON_LIB = True
except ImportError:
    _HAS_TOON_LIB = False

# Regex to strip Telegram-style HTML tags
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# ── Public API ────────────────────────────────────────────────────────────────


def output(data: dict, fmt: str = "toon") -> str:
    """Central dispatcher: format *data* dict as *fmt* string.

    Supported formats:
        - ``"toon"`` (default) — compact key-value serialization
        - ``"rich"`` — terminal output via ``rich`` library
        - ``"text"`` — plain text, HTML tags stripped

    The *data* dict may contain any of the standard keys:
        ``text``, ``buttons``, ``session``, ``state``, ``timestamp``,
        ``success``, ``data``, ``error``.
    """
    fmt = fmt.lower().strip()
    if fmt == "toon":
        return _toon_encode(data)
    elif fmt == "rich":
        return _rich_encode(data)
    elif fmt == "text":
        return _text_encode(data)
    else:
        raise ValueError(f"Unknown output format: {fmt!r}")


def format_screen(
    text: str = "",
    buttons: Optional[List[Dict[str, str]]] = None,
    session: str = "",
    state: str = "",
    fmt: str = "toon",
) -> str:
    """Convenience wrapper: build a screen data dict and format it.

    Parameters
    ----------
    text:
        Screen body text (may contain Telegram HTML).
    buttons:
        List of ``{"label": ..., "callback_data": ...}`` dicts.
    session:
        Session identifier for multi-turn conversations.
    state:
        Current conversation state name.
    fmt:
        Output format (``"toon"``, ``"rich"``, or ``"text"``).
    """
    data: Dict[str, Any] = {"text": text}
    if buttons:
        data["buttons"] = buttons
    if session:
        data["session"] = session
    if state:
        data["state"] = state
    data["timestamp"] = datetime.now().isoformat()
    return output(data, fmt)


def format_result(
    success: bool,
    data: Optional[dict] = None,
    error: str = "",
    fmt: str = "toon",
) -> str:
    """Convenience wrapper: build an operation-result dict and format it.

    Parameters
    ----------
    success:
        Whether the operation succeeded.
    data:
        Optional payload dict with result details.
    error:
        Error message (empty string when *success* is ``True``).
    fmt:
        Output format (``"toon"``, ``"rich"``, or ``"text"``).
    """
    result: Dict[str, Any] = {"success": success}
    if data is not None:
        result["data"] = data
    if error:
        result["error"] = error
    return output(result, fmt)


# ── TOON Encoder ──────────────────────────────────────────────────────────────


def _toon_encode(data: dict) -> str:
    """Serialize *data* to the compact TOON format.

    Falls back to inline encoding when the ``toon-format`` library is not
    available.
    """
    if _HAS_TOON_LIB:
        return toon_lib.encode(data)
    return _toon_encode_inline(data)


def _toon_encode_inline(data: dict, indent: int = 0) -> str:
    """Inline TOON encoder — zero external dependencies.

    Handles strings, ints, floats, booleans, ``None``, nested dicts, and
    lists.  The special ``buttons`` key is rendered as indexed entries:

    .. code-block:: toon

        buttons:
          1: "Label" -> callback_data
          2: "Next" -> next_screen
    """
    lines: List[str] = []
    pad = "  " * indent

    for key, value in data.items():
        if value is None:
            lines.append(f"{pad}{key}: null")
            continue

        # --- buttons: indexed list ---
        if key == "buttons" and isinstance(value, (list, tuple)):
            lines.append(f"{pad}{key}:")
            for idx, btn in enumerate(value, start=1):
                if isinstance(btn, dict):
                    label = btn.get("label", "")
                    cb = btn.get("callback_data", "")
                    safe_label = _toon_escape(label)
                    lines.append(f"{pad}  {idx}: {safe_label} -> {cb}")
                else:
                    lines.append(f"{pad}  {idx}: {_toon_value(btn)}")
            continue

        # --- nested dict ---
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_toon_encode_inline(value, indent + 1))
            continue

        # --- list ---
        if isinstance(value, (list, tuple)):
            lines.append(f"{pad}{key}:")
            for item in value:
                if isinstance(item, dict):
                    child = _toon_encode_inline(item, indent + 1)
                    for child_line in child.split("\n"):
                        lines.append(f"{pad}  {child_line}")
                else:
                    lines.append(f"{pad}  - {_toon_value(item)}")
            continue

        # --- scalar ---
        lines.append(f"{pad}{key}: {_toon_value(value)}")

    return "\n".join(lines)


def _toon_value(value: Any) -> str:
    """Serialize a single value as a TOON literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _toon_escape(value)
    return _toon_escape(str(value))


def _toon_escape(text: str) -> str:
    """Return *text* as a double-quoted TOON string.

    Newlines are escaped to ``\\n`` and backslashes / double-quotes are
    escaped.
    """
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


# ── Rich Encoder ──────────────────────────────────────────────────────────────


def _rich_encode(data: dict) -> str:
    """Format *data* using the ``rich`` library.

    Uses ``Panel`` for the main text, ``Table`` for buttons, and a compact
    metadata line for session/state/timestamp.
    """
    if not _HAS_RICH:
        return _text_encode(data)

    console = Console(width=80, force_terminal=True, highlight=False)
    renderables: List[Any] = []

    text = data.get("text", "")
    if text:
        plain = _strip_html(text)
        renderables.append(Panel(plain, title="Screen", border_style="blue"))

    buttons = data.get("buttons")
    if buttons and isinstance(buttons, (list, tuple)):
        table = Table.grid(padding=(0, 2))
        table.add_column("#", style="dim", justify="right", width=3)
        table.add_column("Label", style="yellow", no_wrap=False)
        table.add_column("Action", style="cyan")
        for idx, btn in enumerate(buttons, start=1):
            if isinstance(btn, dict):
                table.add_row(
                    str(idx),
                    btn.get("label", ""),
                    btn.get("callback_data", ""),
                )
            else:
                table.add_row(str(idx), str(btn), "")
        renderables.append(table)

    # Metadata line
    meta_parts: List[str] = []
    session = data.get("session")
    state = data.get("state")
    ts = data.get("timestamp")
    if session:
        meta_parts.append(f"session: {session}")
    if state:
        meta_parts.append(f"state: {state}")
    if ts:
        meta_parts.append(f"ts: {ts}")
    if meta_parts:
        renderables.append(RichText(" | ".join(meta_parts), style="dim"))

    # Operation result fields
    success = data.get("success")
    if success is not None:
        status = RichText("SUCCESS", style="bold green") if success else RichText("FAILURE", style="bold red")
        renderables.append(status)

    error = data.get("error")
    if error:
        renderables.append(RichText(str(error), style="red"))

    inner_data = data.get("data")
    if inner_data and isinstance(inner_data, dict):
        inner_parts = []
        for k, v in inner_data.items():
            inner_parts.append(f"  {k}: {v}")
        if inner_parts:
            renderables.append(RichText("\n".join(inner_parts), style="green"))

    # Capture output
    with console.capture() as capture:
        for r in renderables:
            console.print(r)

    return capture.get().rstrip("\n")


# ── Text Encoder ──────────────────────────────────────────────────────────────


def _text_encode(data: dict) -> str:
    """Plain-text formatting — strips HTML, minimal structure."""
    lines: List[str] = []

    text = data.get("text", "")
    if text:
        lines.append(_strip_html(text))

    buttons = data.get("buttons")
    if buttons and isinstance(buttons, (list, tuple)):
        lines.append("")
        lines.append("Buttons:")
        for idx, btn in enumerate(buttons, start=1):
            if isinstance(btn, dict):
                label = _strip_html(btn.get("label", ""))
                cb = btn.get("callback_data", "")
                lines.append(f"  {idx}. {label}  [{cb}]")
            else:
                lines.append(f"  {idx}. {btn}")

    meta_parts: List[str] = []
    session = data.get("session")
    state = data.get("state")
    ts = data.get("timestamp")
    if session:
        meta_parts.append(f"session={session}")
    if state:
        meta_parts.append(f"state={state}")
    if ts:
        meta_parts.append(f"ts={ts}")
    if meta_parts:
        lines.append("")
        lines.append(" | ".join(meta_parts))

    success = data.get("success")
    if success is not None:
        lines.append("")
        lines.append("SUCCESS" if success else "FAILURE")

    error = data.get("error")
    if error:
        lines.append(f"Error: {_strip_html(str(error))}")

    inner_data = data.get("data")
    if inner_data and isinstance(inner_data, dict):
        lines.append("")
        for k, v in inner_data.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines).strip()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_html(text: str) -> str:
    """Remove Telegram-style HTML tags (``<b>``, ``<i>``, ``<code>``, etc.).

    Also normalises ``&amp;``, ``&lt;``, ``&gt;`` back to their plain-text
    equivalents.
    """
    result = _HTML_TAG_RE.sub("", text)
    result = result.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return result
