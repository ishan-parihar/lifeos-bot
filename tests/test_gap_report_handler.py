# tests/test_gap_report_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_gapreport_command_sends_enriched_report():
    """The /gapreport command should send an enriched gap report."""
    from bot.handlers.activity import gapreport_command

    update = AsyncMock()
    context = MagicMock()
    update.effective_user.id = 12345
    # Make the loading message awaitable so edit_text works in the handler
    loading_msg = AsyncMock()
    update.message.reply_text.return_value = loading_msg

    mock_gaps = [
        MagicMock(
            severity="medium",
            classification="likely_sleep",
            hours=6.0,
        )
    ]

    with patch("bot.handlers.activity.get_enriched_gaps", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_gaps
        with patch("bot.handlers.activity.render_enriched_gap_report") as mock_render:
            mock_render.return_value = "📊 Gap Report — 1 gap(s)"
            await gapreport_command(update, context)
            # Loading message sent via reply_text
            update.message.reply_text.assert_called_once()
            # Report sent via edit_text on loading message
            loading_msg.edit_text.assert_called_once()
            call_args = loading_msg.edit_text.call_args
            assert "Gap Report" in call_args[0][0]


@pytest.mark.asyncio
async def test_gapreport_command_handles_no_entries():
    """The /gapreport command handles case with no activity entries."""
    from bot.handlers.activity import gapreport_command

    update = AsyncMock()
    context = MagicMock()
    update.effective_user.id = 12345
    loading_msg = AsyncMock()
    update.message.reply_text.return_value = loading_msg

    with patch("bot.handlers.activity.get_enriched_gaps", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = []
        with patch("bot.handlers.activity.render_enriched_gap_report") as mock_render:
            mock_render.return_value = "✅ No gaps detected"
            await gapreport_command(update, context)
            update.message.reply_text.assert_called_once()
            loading_msg.edit_text.assert_called_once()
            call_args = loading_msg.edit_text.call_args
            assert "No gaps" in call_args[0][0]
