"""Single-job OASIS manual-action worker."""

from oasis_worker.contracts import JobResult, JobSpec
from oasis_worker.engine import run_job, verify_runtime_dependencies

__all__ = ["JobResult", "JobSpec", "run_job", "verify_runtime_dependencies"]
