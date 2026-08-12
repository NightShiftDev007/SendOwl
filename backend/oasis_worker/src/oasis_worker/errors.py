class OasisWorkerError(RuntimeError):
    """Base error for an explicitly rejected or failed worker job."""


class ArtifactConflictError(OasisWorkerError):
    """Raised when a job would overwrite an existing SQLite artifact."""


class DependencyContractError(OasisWorkerError):
    """Raised when installed OASIS/CAMEL versions differ from the worker contract."""


class OasisExecutionError(OasisWorkerError):
    """Raised when OASIS cannot complete the manual-action sequence."""


class ArtifactVerificationError(OasisWorkerError):
    """Raised when the persisted SQLite state does not match the submitted job."""
