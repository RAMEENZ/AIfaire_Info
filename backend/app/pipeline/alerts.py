"""Alertes email pour les événements de haute gravité."""
import asyncio
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_GRAVITE_LABELS = {0: "Info", 1: "Vigilance", 2: "Alerte", 3: "Urgence"}


def _send_email_sync(subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM or settings.EMAIL_USER
    msg["To"] = settings.EMAIL_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(settings.EMAIL_SMTP_HOST, settings.EMAIL_SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
        smtp.sendmail(
            settings.EMAIL_FROM or settings.EMAIL_USER,
            [a.strip() for a in settings.EMAIL_TO.split(",")],
            msg.as_string(),
        )


async def send_alert_email(events: list[dict[str, Any]]) -> None:
    """Envoie un email d'alerte si des événements dépassent EMAIL_GRAVITE_MIN."""
    if not settings.EMAIL_ENABLED:
        return
    if not settings.EMAIL_USER or not settings.EMAIL_TO:
        logger.warning("Alert email: EMAIL_USER or EMAIL_TO not set")
        return

    high = [e for e in events if e.get("gravite", 0) >= settings.EMAIL_GRAVITE_MIN]
    if not high:
        return

    lines = []
    for e in sorted(high, key=lambda x: -x.get("gravite", 0))[:10]:
        g = _GRAVITE_LABELS.get(e.get("gravite", 0), "?")
        loc = f" – {e['lieu_nom']}" if e.get("lieu_nom") else ""
        lines.append(f"[{g}{loc}] {e.get('titre', '')[:120]}")
        if e.get("resume_ia"):
            lines.append(f"  → {e['resume_ia'][:200]}")
        lines.append("")

    subject = f"🚨 faire.info – {len(high)} alerte(s) de haute gravité"
    body = (
        f"faire.info – Alerte automatique\n"
        f"{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC\n\n"
        f"{len(high)} événement(s) de haute gravité détecté(s) :\n\n"
        + "\n".join(lines)
        + "\n---\nCeci est une alerte automatique de faire.info.\n"
        "Pour désactiver, mettez EMAIL_ENABLED=false dans votre configuration."
    )

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send_email_sync, subject, body)
        logger.info("Alert email sent: %d high-gravity events", len(high))
    except Exception as exc:
        logger.error("Failed to send alert email: %s", exc)
