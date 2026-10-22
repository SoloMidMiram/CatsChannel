"""Safe publication errors; external exception messages never escape."""


class PublicationError(Exception):
    def __init__(self, code: str = "publication_unavailable") -> None:
        self.code = code
        super().__init__(code)


class DeliveryRejected(PublicationError):
    """Transport proves no delivery occurred (including pre-dispatch validation)."""

    def __init__(self) -> None:
        super().__init__("delivery_rejected")
