"""Transactional discovery ledger for expiring synthetic observations."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, insert, select, update

from ..discovery.domain import PageResult, Status, WatchlistError
from .discovery_repositories import SqlAlchemyWatchlistRepository
from .models import (
    WatchedChannelModel,
)
from .models import (
    discovery_candidates as candidates,
)
from .models import (
    discovery_checkpoints as checkpoints,
)
from .models import (
    discovery_observations as observations,
)
from .models import (
    discovery_scan_runs as runs,
)

_MAX_HISTORY = 20
_MAX_CURSORS = 100
_RUN_RETENTION = timedelta(days=7)


@dataclass(frozen=True)
class ScanLease:
    run_id: str
    owner: str
    version: int
    cursor: str | None
    state: str
    started_at: datetime


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlAlchemyDiscoveryLedger:
    """Mutations are serialized with watchlist edits in the caller's unit of work."""

    def __init__(self, session):
        self.session = session

    async def _row(self, table, *conditions):
        result = await self.session.execute(select(table).where(*conditions))
        return result.mappings().one_or_none()

    async def claim(
        self,
        watchlist_id: str,
        *,
        provider: str,
        fingerprint: str,
        cycle: str,
        expected_watchlist_version: int | None = None,
    ) -> ScanLease:
        if not (
            re.fullmatch(r"[a-z][a-z0-9_]{0,31}", provider)
            and re.fullmatch(r"[a-f0-9]{64}", fingerprint)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,36}", cycle)
        ):
            raise WatchlistError("invalid_scan_scope")

        await SqlAlchemyWatchlistRepository(self.session).lock()
        now = datetime.now(UTC)
        channel = await self.session.get(WatchedChannelModel, watchlist_id)
        if (
            channel is None
            or not channel.enabled
            or channel.retired
            or channel.status != Status.RESOLVED
            or channel.evidence != "synthetic"
        ):
            raise WatchlistError("channel_not_scannable")
        if expected_watchlist_version is not None and channel.version != expected_watchlist_version:
            raise WatchlistError("scan_scope_changed")
        if provider != channel.provider:
            raise WatchlistError("scan_provider_mismatch")
        scope = self._scope(watchlist_id, provider)
        checkpoint = await self._row(checkpoints, *scope)
        run = await self._row(
            runs,
            runs.c.watchlist_id == watchlist_id,
            runs.c.provider == provider,
            runs.c.cycle == cycle,
        )
        if run and _utc(run.expires_at) <= now:
            if checkpoint and checkpoint.run_id == run.id:
                await self.session.execute(
                    update(checkpoints)
                    .where(*scope)
                    .values(run_id=None, cursor=None, seen_cursors=[])
                )
                checkpoint = await self._row(checkpoints, *scope)
            await self.session.execute(delete(runs).where(runs.c.id == run.id))
            run = None

        owner = str(uuid4())
        if run:
            if (
                run.fingerprint != fingerprint
                or run.watchlist_version != channel.version
                or checkpoint is None
                or checkpoint.run_id != run.id
            ):
                raise WatchlistError("scan_scope_changed")
            started_at = _utc(run.expires_at) - _RUN_RETENTION
            if run.state == "completed":
                return ScanLease(run.id, run.owner, run.version, None, run.state, started_at)
            version = run.version + 1
            await self.session.execute(
                update(runs).where(runs.c.id == run.id).values(owner=owner, version=version)
            )
            return ScanLease(run.id, owner, version, checkpoint.cursor, run.state, started_at)

        run_id = str(uuid4())
        await self.session.execute(
            insert(runs).values(
                id=run_id,
                watchlist_id=watchlist_id,
                provider=provider,
                fingerprint=fingerprint,
                cycle=cycle,
                owner=owner,
                version=0,
                watchlist_version=channel.version,
                state="pending",
                items=0,
                attempts=0,
                requests=0,
                expires_at=now + _RUN_RETENTION,
            )
        )
        state = {"run_id": run_id, "cursor": None, "seen_cursors": []}
        if checkpoint is None:
            await self.session.execute(
                insert(checkpoints).values(watchlist_id=watchlist_id, provider=provider, **state)
            )
        else:
            await self.session.execute(update(checkpoints).where(*scope).values(**state))
        return ScanLease(run_id, owner, 0, None, "pending", now)

    async def record_page(
        self,
        lease: ScanLease,
        page: PageResult,
        *,
        items_examined: int,
        requests: int,
        expires_at: datetime,
        coverage_through: datetime | None = None,
    ) -> ScanLease:
        """Commit page observations and progress together, or raise for caller rollback."""
        await SqlAlchemyWatchlistRepository(self.session).lock()
        now = datetime.now(UTC)
        if (
            type(items_examined) is not int
            or not len(page.candidates) <= items_examined <= 10000
            or type(requests) is not int
            or not 0 <= requests <= 10000
            or expires_at.tzinfo is None
            or not now < expires_at <= now + timedelta(days=30)
            or (
                coverage_through is not None
                and (coverage_through.tzinfo is None or coverage_through > now)
            )
        ):
            raise WatchlistError("invalid_page_accounting")
        expires_at = expires_at.astimezone(UTC)
        if coverage_through is not None:
            coverage_through = coverage_through.astimezone(UTC)
        run = await self._row(runs, runs.c.id == lease.run_id)
        if (
            run is None
            or run.owner != lease.owner
            or run.version != lease.version
            or run.state == "completed"
            or _utc(run.expires_at) <= now
        ):
            raise WatchlistError("stale_scan_owner")
        channel = await self.session.get(WatchedChannelModel, run.watchlist_id)
        scope = self._scope(run.watchlist_id, run.provider)
        checkpoint = await self._row(checkpoints, *scope)
        if (
            channel is None
            or channel.version != run.watchlist_version
            or checkpoint is None
            or checkpoint.run_id != run.id
            or checkpoint.cursor != lease.cursor
        ):
            raise WatchlistError("stale_scan_owner")

        state = "backlog"
        cursor = checkpoint.cursor
        seen = list(checkpoint.seen_cursors)
        progress = {}
        if page.checkpoint_may_advance:
            cursor = page.next_cursor
            if cursor is None:
                if coverage_through is None:
                    raise WatchlistError("missing_completed_coverage")
                previous = checkpoint.coverage_through
                progress = {
                    "coverage_through": max(_utc(previous), coverage_through)
                    if previous
                    else coverage_through,
                    "last_full_scan_at": now,
                }
                state = "completed"
                seen = []
            elif cursor in seen or len(seen) >= _MAX_CURSORS:
                raise WatchlistError("scan_cursor_restart_required")
            else:
                seen.append(cursor)

        # Every input is synthetic in this slice. Real API retention requires a separate policy.
        for candidate in page.candidates:
            if candidate.discovery_method != "synthetic":
                raise WatchlistError("discovery_data_category_unapproved")
            if candidate.provider != run.provider:
                raise WatchlistError("candidate_provider_mismatch")
            if candidate.channel_id != channel.channel_id:
                raise WatchlistError("candidate_source_mismatch")
            await self._observe(run, candidate, expires_at, now)

        version = run.version + 1
        result = await self.session.execute(
            update(runs)
            .where(
                runs.c.id == run.id, runs.c.version == lease.version, runs.c.owner == lease.owner
            )
            .values(
                version=version,
                state=state,
                items=run["items"] + items_examined,
                attempts=run.attempts + 1,
                requests=run.requests + requests,
            )
        )
        if result.rowcount != 1:
            raise WatchlistError("stale_scan_owner")
        await self.session.execute(
            update(checkpoints).where(*scope).values(cursor=cursor, seen_cursors=seen, **progress)
        )
        return ScanLease(run.id, lease.owner, version, cursor, state, lease.started_at)

    async def restart(self, lease: ScanLease) -> ScanLease:
        """Discard the cursor chain after expiry, preserving observations and coverage."""
        await SqlAlchemyWatchlistRepository(self.session).lock()
        run = await self._row(runs, runs.c.id == lease.run_id)
        if (
            run is None
            or run.owner != lease.owner
            or run.version != lease.version
            or run.state != "backlog"
            or _utc(run.expires_at) <= datetime.now(UTC)
        ):
            raise WatchlistError("stale_scan_owner")
        scope = self._scope(run.watchlist_id, run.provider)
        checkpoint = await self._row(checkpoints, *scope)
        channel = await self.session.get(WatchedChannelModel, run.watchlist_id)
        if (
            checkpoint is None
            or checkpoint.run_id != run.id
            or channel is None
            or channel.version != run.watchlist_version
        ):
            raise WatchlistError("stale_scan_owner")
        version = run.version + 1
        await self.session.execute(update(runs).where(runs.c.id == run.id).values(version=version))
        await self.session.execute(
            update(checkpoints).where(*scope).values(cursor=None, seen_cursors=[])
        )
        return ScanLease(run.id, run.owner, version, None, run.state, lease.started_at)

    async def coverage(
        self, watchlist_id: str, provider: str
    ) -> tuple[datetime | None, datetime | None]:
        checkpoint = await self._row(checkpoints, *self._scope(watchlist_id, provider))
        if checkpoint is None:
            return None, None
        return (
            _utc(checkpoint.coverage_through) if checkpoint.coverage_through else None,
            _utc(checkpoint.last_full_scan_at) if checkpoint.last_full_scan_at else None,
        )

    async def purge_expired(self, *, now: datetime) -> None:
        if now.tzinfo is None:
            raise WatchlistError("invalid_expiry_clock")
        await SqlAlchemyWatchlistRepository(self.session).lock()
        now = now.astimezone(UTC)
        expired_runs = select(runs.c.id).where(runs.c.expires_at <= now)
        await self.session.execute(
            update(checkpoints)
            .where(checkpoints.c.run_id.in_(expired_runs))
            .values(run_id=None, cursor=None, seen_cursors=[])
        )
        await self.session.execute(delete(runs).where(runs.c.expires_at <= now))
        await self.session.execute(delete(observations).where(observations.c.expires_at <= now))
        await self.session.execute(delete(candidates).where(candidates.c.expires_at <= now))

    async def list_candidates(self, watchlist_id: str, *, now: datetime, limit: int = 100):
        if now.tzinfo is None or type(limit) is not int or not 1 <= limit <= 1000:
            raise WatchlistError("invalid_candidate_query")
        result = await self.session.execute(
            select(candidates)
            .where(
                candidates.c.watchlist_id == watchlist_id,
                candidates.c.expires_at > now.astimezone(UTC),
            )
            .order_by(candidates.c.last_seen.desc(), candidates.c.provider, candidates.c.video_id)
            .limit(limit)
        )
        return tuple(dict(row) for row in result.mappings())

    @staticmethod
    def _scope(watchlist_id, provider):
        return checkpoints.c.watchlist_id == watchlist_id, checkpoints.c.provider == provider

    async def _observe(self, run, candidate, expires_at, now):
        key = (
            candidates.c.provider == candidate.provider,
            candidates.c.video_id == candidate.video_id,
        )
        current = await self._row(candidates, *key)
        if current and _utc(current.expires_at) <= now:
            await self.session.execute(delete(candidates).where(*key))
            current = None
        if current and current.watchlist_id != run.watchlist_id:
            raise WatchlistError("candidate_source_mismatch")

        data = {
            "category": "synthetic",
            "method": candidate.discovery_method,
            "classification": candidate.classification,
            "title": candidate.title,
            "duration_seconds": candidate.duration_seconds,
            "width": candidate.width,
            "height": candidate.height,
            "evidence": list(candidate.evidence),
            "checkpoint_provenance": candidate.checkpoint_provenance,
            "published_at": candidate.published_at.astimezone(UTC).isoformat()
            if candidate.published_at
            else None,
        }
        identity = {"provider": candidate.provider, "video_id": candidate.video_id}
        seen = candidate.observed_at.astimezone(UTC)
        if current is None:
            await self.session.execute(
                insert(candidates).values(
                    **identity,
                    watchlist_id=run.watchlist_id,
                    first_seen=seen,
                    last_seen=seen,
                    expires_at=expires_at,
                    current=data,
                )
            )
        elif seen > _utc(current.last_seen):
            projection = data.copy()
            for field in ("title", "published_at", "duration_seconds", "width", "height"):
                if projection[field] is None:
                    projection[field] = current.current.get(field)
            await self.session.execute(
                update(candidates)
                .where(*key)
                .values(last_seen=seen, expires_at=expires_at, current=projection)
            )
        elif seen < _utc(current.first_seen):
            await self.session.execute(update(candidates).where(*key).values(first_seen=seen))

        history = (
            observations.c.provider == candidate.provider,
            observations.c.video_id == candidate.video_id,
        )
        duplicate = await self._row(observations, *history, observations.c.observed_at == seen)
        if duplicate is None:
            await self.session.execute(
                insert(observations).values(
                    **identity, id=str(uuid4()), observed_at=seen, expires_at=expires_at, data=data
                )
            )
        obsolete = (
            select(observations.c.id)
            .where(*history)
            .order_by(observations.c.observed_at.desc())
            .limit(10000)
            .offset(_MAX_HISTORY)
        )
        await self.session.execute(delete(observations).where(observations.c.id.in_(obsolete)))
