"""Notification delivery service — email (SendGrid) and Slack webhook integration."""

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observatory.core.config.settings import get_settings

logger = structlog.get_logger()


class NotificationService:
    """Delivers notifications via email and Slack."""

    def __init__(self, org_id: uuid.UUID, config: dict[str, Any] | None = None):
        self.org_id = org_id
        self.settings = get_settings()
        self.config = config or {}

    async def send_email(
        self,
        to: list[str],
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send email via SendGrid API."""
        api_key = self.config.get("sendgrid_api_key") or getattr(
            self.settings, "sendgrid_api_key", None
        )
        if not api_key:
            logger.warning("sendgrid_not_configured", org_id=str(self.org_id))
            return False

        from_email = self.config.get("from_email", "observatory@notifications.local")

        payload = {
            "personalizations": [{"to": [{"email": addr} for addr in to]}],
            "from": {"email": from_email, "name": "Observatory"},
            "subject": subject,
            "content": [],
        }

        if text_body:
            payload["content"].append({"type": "text/plain", "value": text_body})
        payload["content"].append({"type": "text/html", "value": html_body})

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=15,
                )
                if resp.status_code in (200, 202):
                    logger.info(
                        "email_sent",
                        org_id=str(self.org_id),
                        recipients=len(to),
                        subject=subject,
                    )
                    return True
                else:
                    logger.error(
                        "email_send_failed",
                        status=resp.status_code,
                        body=resp.text[:500],
                    )
                    return False
        except Exception as e:
            logger.error("email_send_error", error=str(e))
            return False

    async def send_slack(
        self,
        webhook_url: str | None = None,
        message: str = "",
        blocks: list[dict] | None = None,
        channel: str | None = None,
    ) -> bool:
        """Send message via Slack incoming webhook or API."""
        url = webhook_url or self.config.get("slack_webhook_url")
        if not url:
            logger.warning("slack_not_configured", org_id=str(self.org_id))
            return False

        payload: dict[str, Any] = {}
        if channel:
            payload["channel"] = channel
        if blocks:
            payload["blocks"] = blocks
        if message:
            payload["text"] = message

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    logger.info("slack_sent", org_id=str(self.org_id))
                    return True
                else:
                    logger.error(
                        "slack_send_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return False
        except Exception as e:
            logger.error("slack_send_error", error=str(e))
            return False

    async def notify_digest(self, digest: dict[str, Any], recipients: list[str]) -> dict[str, bool]:
        """Send a weekly digest via all configured channels."""
        results = {"email": False, "slack": False}

        title = digest.get("title", "Weekly Intelligence Digest")
        content = digest.get("content", "")

        # Email
        if recipients:
            html_body = self._digest_to_html(title, content, digest)
            results["email"] = await self.send_email(
                to=recipients,
                subject=f"🔭 {title}",
                html_body=html_body,
                text_body=content[:5000],
            )

        # Slack
        if self.config.get("slack_webhook_url"):
            blocks = self._digest_to_slack_blocks(title, content, digest)
            results["slack"] = await self.send_slack(blocks=blocks, message=title)

        return results

    async def notify_alert(self, alert: dict[str, Any], recipients: list[str]) -> dict[str, bool]:
        """Send an urgent alert notification."""
        results = {"email": False, "slack": False}

        severity = alert.get("severity", "medium")
        message = alert.get("message", "Alert from Observatory")
        details = alert.get("details", "")

        # Email for high/critical alerts
        if recipients and severity in ("high", "critical"):
            html_body = (
                f"<h2>⚠️ Observatory Alert: {severity.upper()}</h2>"
                f"<p><strong>{message}</strong></p>"
                f"<pre>{details}</pre>"
                f"<p><small>Generated at {datetime.now(timezone.utc).isoformat()}</small></p>"
            )
            results["email"] = await self.send_email(
                to=recipients,
                subject=f"⚠️ [{severity.upper()}] {message}",
                html_body=html_body,
            )

        # Slack for all alerts
        if self.config.get("slack_webhook_url"):
            emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(
                severity, "⚪"
            )
            results["slack"] = await self.send_slack(
                message=f"{emoji} *[{severity.upper()}]* {message}\n{details}"
            )

        return results

    def _digest_to_html(self, title: str, content: str, digest: dict) -> str:
        sections = content.split("\n\n")
        html_sections = "".join(f"<p>{s}</p>" for s in sections if s.strip())

        return f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h1 style="margin: 0; font-size: 20px;">🔭 {title}</h1>
                <p style="margin: 5px 0 0; opacity: 0.8; font-size: 14px;">
                    {datetime.now(timezone.utc).strftime('%B %d, %Y')}
                </p>
            </div>
            <div style="padding: 20px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px;">
                {html_sections}
            </div>
            <p style="text-align: center; color: #888; font-size: 12px; margin-top: 10px;">
                Generated by Observatory
            </p>
        </div>
        """

    def _digest_to_slack_blocks(
        self, title: str, content: str, digest: dict
    ) -> list[dict]:
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🔭 {title}"},
            },
            {"type": "divider"},
        ]

        # Split content into sections, max 3000 chars per block
        sections = content.split("\n\n")
        current_block = ""
        for section in sections:
            if len(current_block) + len(section) > 2800:
                if current_block:
                    blocks.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": current_block},
                    })
                current_block = section
            else:
                current_block += f"\n\n{section}" if current_block else section

        if current_block:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": current_block},
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Generated by Observatory • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                }
            ],
        })

        return blocks
