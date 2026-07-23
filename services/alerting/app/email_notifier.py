"""ارسال هشدار از طریق ایمیل (FR-ALERT-01)."""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_address: str,
        to_addresses: str,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._to_addresses = [addr.strip() for addr in to_addresses.split(",") if addr.strip()]
        self._enabled = bool(host and username and self._to_addresses)

    def send(self, subject: str, message: str) -> bool:
        if not self._enabled:
            logger.debug("اعلان ایمیل غیرفعال است (تنظیمات SMTP کامل نیست).")
            return False
        email = MIMEText(message, _charset="utf-8")
        email["Subject"] = subject
        email["From"] = self._from_address
        email["To"] = ", ".join(self._to_addresses)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=5.0) as server:
                server.starttls()
                server.login(self._username, self._password)
                server.sendmail(self._from_address, self._to_addresses, email.as_string())
            return True
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("ارسال ایمیل هشدار ناموفق بود: %s", exc)
            return False
