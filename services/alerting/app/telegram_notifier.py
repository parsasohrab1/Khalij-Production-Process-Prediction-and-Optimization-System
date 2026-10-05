"""Send alerts via Telegram (FR-ALERT-01)."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

    def send(self, message: str) -> bool:
        if not self._enabled:
            logger.debug("Telegram notification is disabled (TELEGRAM_BOT_TOKEN/CHAT_ID not set).")
            return False
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            response = httpx.post(url, json={"chat_id": self._chat_id, "text": message}, timeout=5.0)
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.error("Sending the Telegram message failed: %s", exc)
            return False
