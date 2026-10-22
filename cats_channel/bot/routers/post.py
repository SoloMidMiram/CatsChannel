"""Authenticated `/post` entry, selection, and pending-intake handlers."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ...errors import MediaError
from ...intake import IntakeError, IntakePlacement, SubmissionIntakeService
from ...media import youtube_url
from ...persistence import TelegramMessageRef
from ...services.media_service import MediaService
from ...submissions import local_media_from_library_item
from ..context import BotOperation
from ..entry import EntryContractError, ReplyTarget, ReplyTargetResolver, parse_reply_payload
from ..errors import answer_error_safely
from ..flow import (
    FlowLease,
    PrivateEntryContext,
    PrivateEntryStates,
    PrivateFlowCoordinator,
    read_private_entry,
)
from ..telegram_media import TelegramMediaAdapter

POST_PROMPT = (
    "Send one Telegram video or YouTube URL. Select a known source for Telegram files. "
    "Use /cancel to clear it."
)


def _source_keyboard(options) -> InlineKeyboardMarkup | None:
    if not options:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{option.display_name[:40]} ({option.provider})",
                    callback_data=f"postsrc:{option.thread_id}",
                )
            ]
            for option in options
        ]
    )


def _placement(context: PrivateEntryContext) -> IntakePlacement:
    if context.parent_post_id is not None and context.thread_id is not None:
        return IntakePlacement("interactive_reply", context.thread_id, context.parent_post_id)
    return IntakePlacement.normal(context.thread_id)


def create_post_router() -> Router:
    router = Router(name="post_intake")

    @router.message(CommandStart(deep_link=True))
    async def exact_reply_entry(
        message: Message,
        command: CommandObject,
        flow_lease: FlowLease,
        reply_target_resolver: ReplyTargetResolver,
        logger: logging.Logger,
        bot_operation: BotOperation,
    ) -> None:
        try:
            token = parse_reply_payload(command.args or "")
            target = await reply_target_resolver.resolve(token, actor_id=message.from_user.id)
            if target is None:
                raise EntryContractError()
            if not isinstance(target, ReplyTarget):
                raise TypeError("Reply resolver returned an invalid target contract")
            selected = await flow_lease.select(
                PrivateEntryContext(thread_id=target.thread_id, parent_post_id=target.post_id),
                lambda: message.answer(POST_PROMPT),
            )
            if not selected:
                bot_operation.outcome = "superseded"
        except EntryContractError:
            bot_operation.fail("reply_entry_invalid")
            await answer_error_safely(
                message,
                code="reply_entry_invalid",
                logger=logger,
                operation=bot_operation,
                event="bot_error_notification_failure",
            )

    @router.message(Command("post", "submit"))
    async def post_message(
        message: Message,
        flow_lease: FlowLease,
        intake_service: SubmissionIntakeService | None,
    ) -> None:
        if intake_service is None:
            raise IntakeError("intake_unavailable")
        options = await intake_service.list_source_options()
        await flow_lease.select(
            PrivateEntryContext(),
            lambda: message.answer(POST_PROMPT, reply_markup=_source_keyboard(options)),
        )

    @router.callback_query(F.data.startswith("postsrc:"))
    async def select_post_source(
        query: CallbackQuery,
        state: FSMContext,
        flow_coordinator: PrivateFlowCoordinator,
        intake_service: SubmissionIntakeService | None,
        bot_operation: BotOperation,
    ) -> None:
        bot_operation.operation = "post_source_select"
        if intake_service is None or query.message is None:
            raise IntakeError("intake_unavailable")
        thread_id = (query.data or "").removeprefix("postsrc:")
        async with flow_coordinator.continue_current(state) as lease:
            current = await read_private_entry(state)
            if current is None or current.parent_post_id is not None:
                raise IntakeError("intake_superseded")
            options = await intake_service.list_source_options()
            if thread_id not in {option.thread_id for option in options}:
                raise IntakeError("intake_conflict")
            selected = await lease.select(
                PrivateEntryContext(thread_id=thread_id),
                lambda: query.answer("Source selected."),
                invalidate_previous=True,
            )
            if not selected:
                raise IntakeError("intake_superseded")

    @router.message(PrivateEntryStates.reply_entry, F.video)
    async def intake_telegram_video(
        message: Message,
        bot: Bot,
        state: FSMContext,
        flow_coordinator: PrivateFlowCoordinator,
        intake_service: SubmissionIntakeService | None,
        telegram_media_adapter: TelegramMediaAdapter,
        bot_operation: BotOperation,
    ) -> None:
        bot_operation.operation = "post_intake"
        if intake_service is None or message.video is None or message.from_user is None:
            raise IntakeError("intake_unavailable")
        async with flow_coordinator.continue_current(state) as lease:
            context = await read_private_entry(state)
            if context is None:
                raise IntakeError("intake_superseded")
            placement = _placement(context)
            await intake_service.require_compatible_provider(placement, "telegram")
            if not await lease.is_current():
                raise IntakeError("intake_superseded")
            reference = TelegramMessageRef(message.chat.id, message.message_id)
            result = await intake_service.process(
                actor_id=message.from_user.id,
                inbound_reference=reference,
                placement=placement,
                acquire=lambda: telegram_media_adapter.acquire(bot, message.video, reference),
                continue_if=lease.is_current,
                commit_guard=lease.commit_guard,
            )
            # Preserve replacement state after durable success without claiming
            # that an already committed submission was cancelled.
            await lease.clear()
        bot_operation.outcome = f"pending_{result.disposition}"
        await message.answer(f"Accepted as pending submission {result.submission_id}.")

    @router.message(PrivateEntryStates.reply_entry, F.text, ~F.text.startswith("/"))
    async def intake_youtube_url(
        message: Message,
        state: FSMContext,
        flow_coordinator: PrivateFlowCoordinator,
        intake_service: SubmissionIntakeService | None,
        media_service: MediaService,
        bot_operation: BotOperation,
    ) -> None:
        bot_operation.operation = "post_intake"
        if intake_service is None or message.from_user is None:
            raise IntakeError("intake_unavailable")
        async with flow_coordinator.continue_current(state) as lease:
            context = await read_private_entry(state)
            if context is None:
                raise IntakeError("intake_superseded")
            try:
                url = youtube_url((message.text or "").strip())
            except ValueError as error:
                raise MediaError(code="invalid_url") from error
            placement = _placement(context)
            reference = TelegramMessageRef(message.chat.id, message.message_id)

            async def acquire():
                media = local_media_from_library_item(await media_service.acquire_async(url))
                await intake_service.require_compatible_provider(placement, media.source_provider)
                return media

            result = await intake_service.process(
                actor_id=message.from_user.id,
                inbound_reference=reference,
                placement=placement,
                acquire=acquire,
                continue_if=lease.is_current,
                commit_guard=lease.commit_guard,
            )
            await lease.clear()
        bot_operation.outcome = f"pending_{result.disposition}"
        await message.answer(f"Accepted as pending submission {result.submission_id}.")

    return router
