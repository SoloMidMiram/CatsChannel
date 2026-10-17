"""Stable application failures for the source-aware submission workflow."""


class SubmissionError(RuntimeError):
    """Expected submission rejection with a safe, allowlisted code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
