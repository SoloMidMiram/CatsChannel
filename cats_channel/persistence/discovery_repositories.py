"""One durable registry, serialized across processes through a database row."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..discovery.domain import Change, Entry, Registration, ScanPolicy, Status, WatchlistError
from .models import (
    WatchedChannelModel as Channel,
)
from .models import (
    WatchlistControlModel as Control,
)
from .models import (
    WatchlistEventModel as Event,
)
from .models import (
    WatchlistRequestModel as Request,
)


def snapshot(row):
    def utc(value):
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value

    return Entry(
        id=row.id,
        reference=row.reference,
        channel_id=getattr(row, "channel_id", None),
        handle=row.handle,
        display_name=row.display_name,
        enabled=row.enabled,
        retired=row.retired,
        status=Status(row.status),
        evidence=row.evidence,
        retry_after_seconds=row.retry_after_seconds,
        last_resolved_at=utc(row.last_resolved_at),
        policy=ScanPolicy(row.page_budget, row.lookback_days),
        version=row.version,
        created_at=utc(row.created_at),
        updated_at=utc(row.updated_at),
    )


class SqlAlchemyWatchlistRepository:
    def __init__(self, session):
        self.session = session

    async def lock(self):
        insert = sqlite_insert if self.session.bind.dialect.name == "sqlite" else pg_insert
        await self.session.execute(insert(Control).values(id=1, version=0).on_conflict_do_nothing())
        await self.session.execute(
            update(Control).where(Control.id == 1).values(version=Control.version + 1)
        )

    async def row(self, entry_id):
        return await self.session.get(Channel, entry_id) or await self.session.get(
            Request, entry_id
        )

    async def get(self, entry_id):
        row = await self.row(entry_id)
        if isinstance(row, Request) and row.channel_entry_id:
            row = await self.session.get(Channel, row.channel_entry_id)
        return snapshot(row) if row else None

    async def history(self, entry_id, *, limit=100):
        if not 1 <= limit <= 100:
            raise ValueError("invalid_limit")
        rows = await self.session.scalars(
            select(Event)
            .where(Event.entry_id == entry_id)
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(limit)
        )
        return tuple(
            Change(
                row.operator,
                row.operation,
                Status(row.status),
                row.handle,
                row.evidence,
                row.version,
                row.enabled,
                row.retired,
                ScanPolicy(row.page_budget, row.lookback_days),
                row.created_at.replace(tzinfo=UTC)
                if row.created_at.tzinfo is None
                else row.created_at,
            )
            for row in rows
        )

    async def find(self, reference):
        # Historical handle requests are not alias ownership. Always re-resolve handles.
        model = Request if reference.startswith("@") else Channel
        column = model.reference if model is Request else model.channel_id
        query = select(model).where(column == reference)
        if model is Request:
            query = query.where(Request.channel_entry_id.is_(None))
        row = await self.session.scalar(query)
        return snapshot(row) if row else None

    async def list(self, *, after="", limit=100, scanner=False):
        if not 1 <= limit <= 100:
            raise ValueError("invalid_limit")
        query = select(Channel).where(Channel.id > after)
        if scanner:
            query = query.where(
                Channel.enabled.is_(True),
                Channel.retired.is_(False),
                Channel.status == Status.RESOLVED,
            )
        rows = list(await self.session.scalars(query.order_by(Channel.id).limit(limit)))
        if not scanner:
            rows += list(
                await self.session.scalars(
                    select(Request)
                    .where(Request.id > after, Request.channel_entry_id.is_(None))
                    .order_by(Request.id)
                    .limit(limit)
                )
            )
        return tuple(snapshot(row) for row in sorted(rows, key=lambda row: row.id)[:limit])

    async def ensure_capacity(self, capacity):
        channels = await self.session.scalar(
            select(func.count()).select_from(Channel).where(Channel.retired.is_(False))
        )
        requests = await self.session.scalar(
            select(func.count())
            .select_from(Request)
            .where(Request.retired.is_(False), Request.channel_entry_id.is_(None))
        )
        if channels + requests >= capacity:
            raise WatchlistError("capacity_exceeded")

    async def add(self, reference, capacity):
        await self.ensure_capacity(capacity)
        cls = Request if reference.startswith("@") else Channel
        values = {
            "id": str(uuid4()),
            "reference": reference,
            "status": Status.UNRESOLVED,
            "evidence": "none",
            "enabled": False,
            "retired": False,
        }
        if cls is Channel:
            values.update(channel_id=reference, provider="youtube")
        row = cls(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def event(self, row, operator, operation):
        self.session.add(
            Event(
                id=str(uuid4()),
                entry_id=row.id,
                operator=operator.name,
                operation=operation,
                status=row.status,
                handle=row.handle,
                evidence=row.evidence,
                version=row.version,
                enabled=row.enabled,
                retired=row.retired,
                page_budget=row.page_budget,
                lookback_days=row.lookback_days,
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        # Keep the latest 100 bounded events per entry, retaining the identity itself forever.
        keep = (
            select(Event.id)
            .where(Event.entry_id == row.id)
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(100)
        )
        await self.session.execute(
            delete(Event).where(Event.entry_id == row.id, Event.id.not_in(keep))
        )

    async def save(self, row):
        row.version += 1
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return snapshot(row)

    async def apply_resolution(self, reference, before, result, operator, capacity, started_at):
        current = await self.find(reference)
        if before is not None and current is None:
            raise WatchlistError("stale_resolution")
        if current and (before is None or current.version != before.version):
            if before is None:
                return Registration(await self.get(current.id), "already_known")
            raise WatchlistError("stale_resolution")
        if current and current.retired:
            raise WatchlistError("retired")
        row = await self.row(current.id) if current else None
        if result.status == Status.RESOLVED:
            known = await self.find(result.channel_id)
            if known and known.retired:
                raise WatchlistError("retired")
            if known and known.updated_at > started_at:
                if isinstance(row, Request):
                    row.channel_entry_id, row.retired = known.id, True
                    row.status, row.evidence = result.status, result.evidence
                    row.last_resolved_at = datetime.now(UTC)
                    await self.save(row)
                    await self.event(row, operator, "resolved")
                return Registration(known, "already_known")
            if known:
                target = await self.row(known.id)
            elif row and reference.startswith("@"):
                # Transfer the request's slot before inserting the canonical identity.
                row.retired = True
                await self.session.flush()
                target = await self.add(result.channel_id, capacity)
            else:
                target = await self.add(result.channel_id, capacity)
            outcome = (
                "registered"
                if not known
                else ("renamed" if target.handle != result.handle else "already_known")
            )
            if row and row.id != target.id:
                row.channel_entry_id = target.id
                row.status, row.evidence = result.status, result.evidence
                row.last_resolved_at = datetime.now(UTC)
                row.retired = True
                await self.save(row)
                await self.event(row, operator, "resolved")
            if not known:
                target.enabled = True
                if row:
                    target.enabled = row.enabled
                    target.page_budget = row.page_budget
                    target.lookback_days = row.lookback_days
            target.handle = result.handle
            target.display_name = result.display_name
            target.last_resolved_at = datetime.now(UTC)
            row = target
        else:
            row = row or await self.add(reference, capacity)
            outcome = result.status.value
        row.status = result.status
        row.evidence = result.evidence
        row.retry_after_seconds = result.retry_after_seconds
        entry = await self.save(row)
        await self.event(row, operator, outcome)
        return Registration(entry, outcome)

    async def refresh(self, before, result, operator):
        row = await self.row(before.id)
        if row.version != before.version:
            raise WatchlistError("stale_resolution")
        row.status, row.evidence = result.status, result.evidence
        row.retry_after_seconds = result.retry_after_seconds
        if result.status == Status.RESOLVED:
            row.handle, row.display_name = result.handle, result.display_name
            row.last_resolved_at = datetime.now(UTC)
        elif result.status == Status.UNAVAILABLE:
            row.handle, row.display_name = None, None
        entry = await self.save(row)
        await self.event(row, operator, "refresh_resolution")
        return entry

    async def change(self, entry_id, operator, operation, enabled, policy):
        entry = await self.get(entry_id)
        if entry is None:
            raise WatchlistError("not_found")
        row = await self.row(entry.id)
        if row.retired:
            raise WatchlistError("retired")
        if enabled is not None:
            row.enabled = enabled
        if policy is not None:
            row.page_budget, row.lookback_days = policy.page_budget, policy.lookback_days
        if operation == "retire":
            row.retired, row.enabled = True, False
        result = await self.save(row)
        await self.event(row, operator, operation)
        return result
