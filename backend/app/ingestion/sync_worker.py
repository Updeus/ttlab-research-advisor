from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import create_db_and_tables, engine
from app.ingestion.sync import (
    ATOMIC_GENERATION_PROMOTION_IMPLEMENTED,
    SOURCE,
    as_utc,
    ensure_sync_state,
    execute_ttlab_discovery_check,
    execute_ttlab_sync,
    get_sync_state,
    iso_utc,
    utc_now,
)


def daily_time(settings: Settings) -> tuple[int, int]:
    minute, hour, _day, _month, _weekday = settings.sync_cron.split()
    return int(hour), int(minute)


def scheduled_boundary(settings: Settings, now: datetime) -> datetime:
    zone = ZoneInfo(settings.sync_timezone)
    local_now = now.astimezone(zone)
    hour, minute = daily_time(settings)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate > local_now:
        candidate -= timedelta(days=1)
    return candidate.astimezone(UTC)


def next_scheduled_run(settings: Settings, now: datetime) -> datetime:
    zone = ZoneInfo(settings.sync_timezone)
    local_now = now.astimezone(zone)
    hour, minute = daily_time(settings)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def scheduled_sync_due(settings: Settings, session: Session, now: datetime) -> bool:
    if (
        not settings.sync_enabled
        or settings.sync_execution_mode != "offline_single_writer"
        or settings.service_role != "offline_worker"
    ):
        return False
    state = get_sync_state(session)
    if settings.sync_run_on_startup and (state is None or state.last_run_id is None):
        return True
    zone = ZoneInfo(settings.sync_timezone)
    local_now = now.astimezone(zone)
    hour, minute = daily_time(settings)
    today_schedule = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now < today_schedule:
        return False
    boundary = today_schedule.astimezone(UTC)
    attempts = [
        value
        for value in (
            as_utc(state.last_success_at) if state else None,
            as_utc(state.last_failure_at) if state else None,
        )
        if value is not None
    ]
    return not attempts or max(attempts) < boundary


def update_next_scheduled_at(session: Session, settings: Settings, now: datetime) -> None:
    state = ensure_sync_state(session)
    enabled = bool(
        settings.sync_enabled
        and settings.sync_execution_mode == "offline_single_writer"
        and settings.service_role == "offline_worker"
    )
    next_run = next_scheduled_run(settings, now).replace(tzinfo=None) if enabled else None
    if state.next_scheduled_at != next_run:
        state.next_scheduled_at = next_run
        state.updated_at = utc_now()
        session.add(state)
        session.commit()


def run_worker(settings: Settings) -> None:
    if settings.service_role != "offline_worker" or settings.sync_execution_mode != "offline_single_writer":
        print(
            json.dumps(
                {
                    "event": "sync_worker_not_started",
                    "reason": "discovery_worker_not_configured",
                    "required_service_role": "offline_worker",
                    "required_execution_mode": "offline_single_writer",
                    "service_role": settings.service_role,
                    "execution_mode": settings.sync_execution_mode,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return
    create_db_and_tables()
    print(
        json.dumps(
            {
                "event": "sync_worker_started",
                "source": SOURCE,
                "schedule_enabled": settings.sync_enabled,
                "execution_mode": settings.sync_execution_mode,
                "service_role": settings.service_role,
                "single_writer": True,
                "schedule": settings.sync_cron,
                "timezone": settings.sync_timezone,
                "poll_seconds": settings.sync_worker_poll_seconds,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    while True:
        now = datetime.now(UTC)
        with Session(engine) as session:
            update_next_scheduled_at(session, settings, now)
            state = get_sync_state(session)
            manual_pending = bool(settings.sync_enabled and state and state.manual_requested_at)
            due = scheduled_sync_due(settings, session, now)
            if manual_pending or due:
                trigger = "manual" if manual_pending else "scheduled"
                requested_by = state.manual_requested_by if manual_pending and state else None
                result = execute_ttlab_discovery_check(
                    session,
                    settings=settings,
                    trigger=trigger,
                    requested_by=requested_by,
                )
                print(json.dumps({"event": "sync_run_finished", **result}, sort_keys=True), flush=True)
                update_next_scheduled_at(session, settings, datetime.now(UTC))
        time.sleep(settings.sync_worker_poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run scheduled TTLAB catalogue ingestion.")
    parser.add_argument("--once", action="store_true", help="Run one synchronization immediately and exit.")
    parser.add_argument("--trigger", choices=["cli", "scheduled", "manual"], default="cli")
    parser.add_argument("--requested-by", default=None)
    parser.add_argument("--status", action="store_true", help="Print worker scheduling state and exit.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    if args.status:
        create_db_and_tables()
        with Session(engine) as session:
            state = get_sync_state(session)
            effective_enabled = bool(
                settings.sync_enabled
                and settings.sync_execution_mode == "offline_single_writer"
                and settings.service_role == "offline_worker"
            )
            print(
                json.dumps(
                    {
                        "enabled": effective_enabled,
                        "configured_enabled": settings.sync_enabled,
                        "effective_enabled": effective_enabled,
                        "disabled_reason": (
                            None if effective_enabled else "discovery_worker_not_configured"
                        ),
                        "execution_mode": settings.sync_execution_mode,
                        "service_role": settings.service_role,
                        "schedule": settings.sync_cron,
                        "timezone": settings.sync_timezone,
                        "manual_request_pending": bool(state and state.manual_requested_at),
                        "next_scheduled_at": iso_utc(state.next_scheduled_at) if state else None,
                    },
                    indent=2,
                )
            )
        return
    if args.once:
        create_db_and_tables()
        with Session(engine) as session:
            result = execute_ttlab_discovery_check(
                session,
                settings=settings,
                trigger=args.trigger,
                requested_by=args.requested_by,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        if result.get("status") not in {"succeeded", "skipped"}:
            raise SystemExit(1)
        return
    try:
        run_worker(settings)
    except KeyboardInterrupt:
        print(json.dumps({"event": "sync_worker_stopped", "source": SOURCE}), flush=True)


if __name__ == "__main__":
    main()
