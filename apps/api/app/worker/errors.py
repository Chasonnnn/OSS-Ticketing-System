from __future__ import annotations


class JobError(RuntimeError):
    pass


class PermanentJobError(JobError):
    pass
