"""Monitoring Celery tasks.

Phase 2d: Scheduled reminder scanning and email notification.
"""
import logging
from datetime import datetime, timezone

from celery import shared_task

from app.db.session import async_session_maker
from app.services.email_service import email_service

_log = logging.getLogger(__name__)


@shared_task(name="app.tasks.monitoring.scan_pending_events")
def scan_pending_events() -> dict:
    """Scan all pending monitoring events and send email reminders."""
    import asyncio

    async def _run():
        from sqlalchemy import select, update
        from app.models.agent import MonitoringEvent

        async with async_session_maker() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(MonitoringEvent).where(
                    MonitoringEvent.status == "pending",
                    MonitoringEvent.scheduled_at <= now,
                    MonitoringEvent.retry_count < 3,
                ).limit(50)
            )
            events = result.scalars().all()
            sent = 0
            failed = 0

            for evt in events:
                try:
                    payload = evt.payload or {}
                    await email_service.send_email(
                        db=db,
                        to_email=payload.get("email", ""),
                        subject=f"【MediCareAI】{evt.event_type.replace('_', ' ')}",
                        html_content=f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;">
<div style="max-width:500px;margin:0 auto;padding:20px;">
<h2>📋 提醒</h2>
<p>{payload.get('description', '您有一个新的健康提醒')}</p>
<p style="color:#999;">计划 ID: {evt.plan_id}</p>
</div></body></html>""",
                    )
                    evt.triggered_at = now
                    evt.status = "sent"
                    sent += 1
                except Exception as e:
                    evt.retry_count = (evt.retry_count or 0) + 1
                    evt.error_message = str(e)
                    failed += 1

            await db.commit()
            _log.info(f"[MONITOR] scan complete: sent={sent} failed={failed}")
            return {"sent": sent, "failed": failed}

    return asyncio.run(_run())
