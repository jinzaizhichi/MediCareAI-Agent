"""Health planning Celery tasks.

Phase 2b: AI health profile generation from patient history.
"""
import logging

from celery import shared_task

from app.db.session import async_session_maker
from app.services.agents import PlanningAgent

_log = logging.getLogger(__name__)


@shared_task(name="app.tasks.planning.generate_health_profile")
def generate_health_profile(patient_id: str) -> dict:
    """Generate AI health summary from patient's medical history (async)."""
    import asyncio

    async def _run():
        agent = PlanningAgent()
        return await agent.generate_health_profile(patient_id)

    try:
        result = asyncio.run(_run())
        _log.info(f"[PLANNING] health_profile generated for patient={patient_id}")
        return result
    except Exception as e:
        _log.error(f"[PLANNING] health_profile failed for patient={patient_id}: {e}")
        return {"message": f"Failed: {e}"}
