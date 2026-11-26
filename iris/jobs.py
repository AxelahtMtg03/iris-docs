"""Tâches de fond : progression, annulation et erreurs."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .errors import Cancelled, IrisError, message

log = logging.getLogger("iris")
MAX_KEPT = 50


@dataclass
class Job:
    kind: str  # "document" ou "model"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"  # queued, running, done, error, cancelled
    progress: float = 0.0
    stage: str = ""
    label: str = ""
    result: Any = None
    error: IrisError | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)

    def update(self, fraction: float, stage: str = "") -> None:
        self.progress = max(self.progress, min(1.0, fraction))
        if stage:
            self.stage = stage

    def to_dict(self, lang: str = "fr") -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "progress": round(self.progress, 4),
            "stage": self.stage,
        }
        if self.error:
            data["error"] = {
                "code": self.error.code,
                "message": message(self.error.code, lang, **self.error.params),
                "detail": self.error.detail,
            }
        return data


class JobManager:
    """Une seule tâche de chaque sorte à la fois : un document n'attend pas un téléchargement."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pools = {
            kind: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"iris-{kind}")
            for kind in ("document", "model")
        }

    def submit(self, kind: str, work: Callable[[Job], Any], label: str = "") -> Job:
        job = Job(kind, label=label)
        with self._lock:
            old = [j.id for j in self._jobs.values() if j.finished.is_set()]
            for job_id in old[: max(0, len(old) - MAX_KEPT)]:
                del self._jobs[job_id]
            self._jobs[job.id] = job
        self._pools[kind].submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Callable[[Job], Any]) -> None:
        try:
            if job.cancel.is_set():
                raise Cancelled()
            job.status = "running"
            job.result = work(job)
            job.progress = 1.0
            job.status = "done"
        except Cancelled:
            job.status = "cancelled"
        except IrisError as exc:
            log.warning("%s : %s %s", job.label, exc.code, exc.detail)
            job.error, job.status = exc, "error"
        except Exception as exc:
            log.exception("Erreur inattendue (%s)", job.label)
            job.error = IrisError("internal", f"{type(exc).__name__}: {exc}")
            job.status = "error"
        finally:
            job.finished.set()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self, kind: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.kind == kind and not j.finished.is_set()]

    def shutdown(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                job.cancel.set()
        for pool in self._pools.values():
            pool.shutdown(wait=True)
