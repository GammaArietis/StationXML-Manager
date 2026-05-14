from dataclasses import dataclass, field
from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal


@dataclass
class Job:
    name: str
    function: Callable[..., Any]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


class JobWorker(QObject):
    progress = pyqtSignal(object)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, job: Job):
        super().__init__()
        self._job = job
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            kwargs = dict(self._job.kwargs)
            kwargs["report_progress"] = self.progress.emit
            kwargs["is_cancelled"] = self.is_cancelled
            result = self._job.function(*self._job.args, **kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class JobRunner(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._running_jobs = {}

    def is_running(self, job_name: str) -> bool:
        job_ctx = self._running_jobs.get(job_name)
        if not job_ctx:
            return False
        return job_ctx["thread"].isRunning()

    def run_job(self, job: Job, on_progress=None, on_finished=None, on_error=None) -> bool:
        if self.is_running(job.name):
            return False

        thread = QThread(self)
        worker = JobWorker(job)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        if on_progress:
            worker.progress.connect(on_progress)
        if on_finished:
            worker.finished.connect(on_finished)
        if on_error:
            worker.error.connect(on_error)

        def _cleanup():
            if worker:
                worker.deleteLater()
            self._running_jobs.pop(job.name, None)

        thread.finished.connect(_cleanup)
        self._running_jobs[job.name] = {"thread": thread, "worker": worker}
        thread.start()
        return True

    def cancel_job(self, job_name: str):
        job_ctx = self._running_jobs.get(job_name)
        if not job_ctx:
            return
        job_ctx["worker"].cancel()

    def shutdown(self, wait_ms: int = 3000):
        for job_ctx in list(self._running_jobs.values()):
            worker = job_ctx["worker"]
            thread = job_ctx["thread"]
            worker.cancel()
            thread.quit()
            thread.wait(wait_ms)
