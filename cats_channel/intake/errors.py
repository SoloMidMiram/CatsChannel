"""Safe application failures for bot submission intake."""

ERROR_CODES = frozenset(
    {
        "intake_conflict",
        "intake_persistence",
        "intake_superseded",
        "intake_unavailable",
    }
)


class IntakeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if code in ERROR_CODES else "intake_unavailable"
        super().__init__(self.code)
