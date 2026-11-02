from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReviewItem:
    id: str
    submission_id: str
    review_chat_id: int
    destination_chat_id: int
    message_id: int | None
    delivery_state: str
    decision_state: str
    version: int
    reviewer_id: int | None
    reviewed_at: datetime | None
    publication_id: str | None
    error_category: str | None
    decision_action: str | None = None
    rejection_reason: str | None = None


class ReviewError(Exception):
    def __init__(self, code="review_unavailable"):
        self.code = code
        super().__init__(code)
