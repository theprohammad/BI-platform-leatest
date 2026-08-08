"""In-process async job runner behind a stable interface (Blueprint §1.7).
S6: job state write-through to the `jobs` table — the DB is the source of
truth (survives restart/replicas); the dict is a same-process cache.
TODO(scale): arq/Redis workers; `start`/`status` signatures unchanged (rule 4).
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field

from app.core.events import Event, bus
from app.core.logging import get_logger

log = get_logger("runner")


@dataclass
class Job:
    id: str
    status: str = "running"          # running | completed | failed
    result: dict = field(default_factory=dict)
    error: str | None = None
    started_at: float = field(default_factory=time.time)


class TaskRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._aux_tasks: set = set()

    def start(self, coro_factory, *, run_id: str | None = None) -> str:
        job_id = run_id or uuid.uuid4().hex[:12]
        job = Job(id=job_id)
        self._jobs[job_id] = job

        async def wrapper():
            from app.db import session as db
            await db.upsert_job(job_id, status="running")

            async def heartbeat():
                while job.status == "running":
                    await asyncio.sleep(15)
                    if job.status == "running":
                        await db.upsert_job(job_id, status="running")

            hb = asyncio.create_task(heartbeat())
            self._aux_tasks.add(hb)          # hold refs (GC safety)
            hb.add_done_callback(self._aux_tasks.discard)
            try:
                job.result = await coro_factory()
                job.status = "completed"
                await db.upsert_job(job_id, status="completed", result=job.result)
            except Exception as exc:
                log.exception("job %s failed", job_id)
                job.status = "failed"
                job.error = str(exc)
                await db.upsert_job(job_id, status="failed", error=str(exc))
                await bus.publish(Event("run.failed", job_id, {"error": str(exc)}))
            finally:
                hb.cancel()
                bus.clear_run(job_id)      # B3 leak fix: table is now the record

        task = asyncio.create_task(wrapper())
        self._aux_tasks.add(task)          # hold refs (GC safety)
        task.add_done_callback(self._aux_tasks.discard)
        return job_id

    def status(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


runner = TaskRunner()
