import asyncio
import threading
from pathlib import Path

from ..adapters.process import CancellationToken
from ..config import Settings
from ..errors import MediaError
from ..library import store_download
from ..media import probe as probe_media
from ..models import LibraryItem


class MediaService:
    """Single acquisition path shared by CLI and Telegram handlers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._worker = threading.Semaphore(1)

    def acquire(
        self,
        url: str,
        *,
        token: CancellationToken | None = None,
    ) -> LibraryItem:
        self._acquire_worker(token)
        try:
            record = store_download(self.settings, url, token=token)
            manifest = record["manifest"]
            file_record = manifest["file"]
            item_path = str(record["item_path"])
            media_path = self.settings.download_dir / Path(item_path) / str(file_record["name"])
            if not media_path.is_file():
                raise MediaError("Validated media disappeared before use.", code="cache_corrupt")
            return LibraryItem(
                status=str(record["status"]),
                item_path=item_path,
                media_path=media_path,
                manifest=manifest,
            )
        finally:
            self._worker.release()

    def _acquire_worker(self, token: CancellationToken | None) -> None:
        while not self._worker.acquire(timeout=0.1):
            if token is not None and token.cancelled:
                raise MediaError(code="cancelled")
        if token is not None and token.cancelled:
            self._worker.release()
            raise MediaError(code="cancelled")

    def probe(
        self,
        url: str,
        *,
        token: CancellationToken | None = None,
    ) -> dict[str, object]:
        self._acquire_worker(token)
        try:
            return probe_media(self.settings, url, token=token)
        finally:
            self._worker.release()

    async def acquire_async(self, url: str) -> LibraryItem:
        token = CancellationToken()
        task = asyncio.create_task(asyncio.to_thread(self.acquire, url, token=token))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            token.cancel()
            worker_error = await self._drain_cancelled_worker(task)
            if isinstance(worker_error, MediaError):
                if worker_error.code != "cancelled":
                    raise worker_error
            elif worker_error is not None and not isinstance(worker_error, asyncio.CancelledError):
                raise worker_error
            raise

    async def probe_async(self, url: str) -> dict[str, object]:
        token = CancellationToken()
        task = asyncio.create_task(asyncio.to_thread(self.probe, url, token=token))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            token.cancel()
            worker_error = await self._drain_cancelled_worker(task)
            if isinstance(worker_error, MediaError):
                if worker_error.code != "cancelled":
                    raise worker_error
            elif worker_error is not None and not isinstance(worker_error, asyncio.CancelledError):
                raise worker_error
            raise

    @staticmethod
    async def _drain_cancelled_worker(task: asyncio.Task[object]) -> BaseException | None:
        """Ignore repeated caller cancellation until the owned worker has stopped."""
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:  # noqa: BLE001 - result is retrieved and classified below
                break
        try:
            task.result()
        except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001
            return error
        return None
