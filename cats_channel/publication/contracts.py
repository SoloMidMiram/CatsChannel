"""Small repository and transport contracts; no ORM or aiogram dependencies."""

from datetime import datetime
from typing import Protocol

from ..persistence.entities import CatVideoSubmission, TelegramMessageRef
from .entities import Attempt, MarkupState, Publication, State


class PublicationTransport(Protocol):
    async def send(
        self, submission: CatVideoSubmission, *, parent: TelegramMessageRef | None
    ) -> TelegramMessageRef: ...

    async def install_markup(
        self, reference: TelegramMessageRef, *, token: str, child: TelegramMessageRef | None
    ) -> None: ...


class PublicationRepository(Protocol):
    async def get(self, publication_id: str) -> Publication | None: ...

    async def get_for_post(self, post_id: str, chat_id: int) -> Publication | None: ...

    async def create(self, post_id: str, chat_id: int) -> Publication: ...

    async def transition(
        self, publication: Publication, state: State, *, category: str | None = None
    ) -> Publication: ...

    async def claim(self, publication: Publication, now: datetime) -> Attempt: ...

    async def finish(
        self,
        publication: Publication,
        attempt: Attempt,
        state: State,
        now: datetime,
        *,
        category: str | None = None,
        recovery: str | None = None,
    ) -> Publication: ...

    async def current_attempt(self, publication: Publication) -> Attempt | None: ...

    async def list_sending(self) -> tuple[Publication, ...]: ...

    async def set_markup(self, publication_id: str, status: MarkupState) -> None: ...

    async def replace_token(self, publication_id: str, digest: str) -> None: ...

    async def set_navigation(self, publication_id: str, child_post_id: str) -> None: ...
