from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

from catora_api.config import Settings


class AuthMailer(Protocol):
    async def send_invitation(self, recipient: str, link: str) -> None: ...
    async def send_password_reset(self, recipient: str, link: str) -> None: ...


class SmtpAuthMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _send(self, recipient: str, subject: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text)

        def deliver() -> None:
            with smtplib.SMTP(
                self._settings.smtp_host, self._settings.smtp_port, timeout=10
            ) as smtp:
                smtp.send_message(message)

        await asyncio.to_thread(deliver)

    async def send_invitation(self, recipient: str, link: str) -> None:
        await self._send(recipient, "You are invited to Catora", f"Accept your invitation: {link}")

    async def send_password_reset(self, recipient: str, link: str) -> None:
        await self._send(recipient, "Reset your Catora password", f"Reset your password: {link}")
