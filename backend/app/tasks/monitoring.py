"""Monitoring Celery tasks.

Phase 2d: Heartbeat-based scheduled reminder scanning.
Pattern adapted from openclaw heartbeat-runner.
"""
import logging
from datetime import datetime, timezone, time as dt_time

from celery import shared_task
from sqlalchemy import select

from app.db.session import async_session_maker
from app.services.email_service import email_service

_log = logging.getLogger("heartbeat")


@shared_task(name="app.tasks.monitoring.scan_pending_events")
def scan_pending_events() -> dict:
    """Heartbeat task: scan pending events and send reminders.

    Features (openclaw pattern):
    - skipWhenBusy: defer if patient in active diagnosis
    - retry: max 3 attempts per event
    - batch: limit 50 per scan
    """
    import asyncio

    async def _run():
        from app.models.agent import MonitoringEvent, AgentSession

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
            skipped_busy = 0
            failed = 0

            for evt in events:
                # skipWhenBusy: defer if patient in active diagnosis
                busy_result = await db.execute(
                    select(AgentSession).where(
                        AgentSession.user_id == evt.patient_id,
                        AgentSession.status == "ACTIVE",
                        AgentSession.session_type == "DIAGNOSIS",
                    ).limit(1)
                )
                if busy_result.scalar_one_or_none():
                    skipped_busy += 1
                    continue

                try:
                    payload = evt.payload or {}
                    desc = payload.get("description", payload.get("name", "医疗提醒"))

                    await email_service.send_email(
                        db=db,
                        to_email=payload.get("email", ""),
                        subject=f"【MediCareAI】{evt.event_type}",
                        html_content=f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;">
<div style="max-width:500px;margin:0 auto;padding:20px;border:1px solid #eee;border-radius:8px;">
<h2 style="color:#E8956A;">📋{evt.event_type}</h2>
<p style="font-size:16px;">{desc}</p>
<p style="color:#999;font-size:12px;">自动化提醒 · 如有疑问请联系平台管理员</p>
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
            _log.info(f"[HEARTBEAT] sent={sent} skipped_busy={skipped_busy} failed={failed}")
            return {"sent": sent, "skipped_busy": skipped_busy, "failed": failed}

    return asyncio.run(_run())
