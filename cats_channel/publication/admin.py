"""Offline operator entry point. Stop the bot before using this recovery tool."""

import argparse
import asyncio
import json

from aiogram import Bot

from ..adapters.aiogram_publisher import AiogramPublisher
from ..config import Settings
from ..persistence import Database, TelegramMessageRef
from ..reply_chains.service import ReplyChainService
from .errors import PublicationError
from .service import PublicationService


async def execute(settings: Settings, args: argparse.Namespace):
    """Local operator credentials authorize this operation; never expose via public input."""
    settings.require_bot()
    destination = int(settings.channel_id or "")
    database = Database.from_settings(settings)
    bot = Bot(settings.bot_token.get_secret_value())
    try:
        service = PublicationService(
            database.unit_of_work,
            reply_chains=ReplyChainService(database.unit_of_work, destination_chat_id=destination),
            transport=AiogramPublisher(bot, settings, destination_chat_id=destination),
            destination_chat_id=destination,
        )
        if args.action == "recover-abandoned":
            await service.recover_abandoned()
            return {"status": "reconciled_to_unknown"}
        if not args.publication_id:
            raise PublicationError("publication_id_required")
        if args.action == "confirm":
            if not args.message_id:
                raise PublicationError("confirmed_reference_required")
            result = await service.reconcile(
                args.publication_id, reference=TelegramMessageRef(destination, args.message_id)
            )
        elif args.action == "prove-non-delivery":
            result = await service.reconcile(args.publication_id, non_delivery_proven=True)
        elif args.action == "requeue":
            result = await service.requeue_failed(args.publication_id)
        elif args.action == "repair-markup":
            result = await service.repair_markup(args.publication_id)
        else:
            result = await service._get(args.publication_id)
        return {
            "publication_id": result.id,
            "post_id": result.post_id,
            "state": result.state,
            "markup_status": result.markup_status,
            "error_category": result.error_category,
        }
    finally:
        await bot.session.close()
        await database.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "status",
            "recover-abandoned",
            "confirm",
            "prove-non-delivery",
            "requeue",
            "repair-markup",
        ],
    )
    parser.add_argument("publication_id", nargs="?")
    parser.add_argument("--message-id", type=int)
    parser.add_argument(
        "--bot-stopped",
        action="store_true",
        required=True,
        help="assert exclusive local operator ownership",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(execute(Settings(), args))
    except Exception:  # noqa: BLE001 - never print credentials or API exceptions
        print(json.dumps({"status": "error", "category": "publication_recovery_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
