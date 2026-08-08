from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Never

from cohestra import __version__

from .db import (
    ESCALATION_INCIDENT_TYPES,
    ESCALATION_STATES,
    EVENT_KINDS,
    JOIN_POLICIES,
    JOIN_REQUEST_STATUSES,
    MANUAL_ESCALATION_RESOLUTION_CODES,
    WORK_CLAIM_STATES,
    BridgeError,
    ConversationBridge,
)


def _configure_stdio() -> None:
    # JSON is a machine interface. Force one encoding so redirected Windows
    # output does not silently switch between the active OEM and ANSI code pages.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise BridgeError("invalid_arguments", message)


def _emit(data: Any, *, ok: bool = True, stream: Any = sys.stdout) -> None:
    payload = {"ok": ok, "data": data} if ok else {"ok": False, "error": data}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), file=stream)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="cohestra-bridge",
        description="Local task-scoped AI agent coordination bridge",
    )
    parser.add_argument("--db", type=Path, required=True, help="Explicit SQLite database path")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize or verify the database schema")

    task_create = commands.add_parser("task-create", help="Create a task and join its creator")
    task_create.add_argument("--task-id", required=True)
    task_create.add_argument("--title", required=True)
    task_create.add_argument("--agent", required=True)
    task_create.add_argument("--join-policy", choices=JOIN_POLICIES, default="private")
    task_create.add_argument("--discovery-summary")
    task_create.add_argument("--objective")
    task_create.add_argument("--acceptance-criterion", action="append", default=[])
    task_create.add_argument("--worklog-path")

    task_join = commands.add_parser("task-join", help="Add an Agent to an existing task")
    task_join.add_argument("--task-id", required=True)
    task_join.add_argument("--agent", required=True, help="Agent to add")
    task_join.add_argument(
        "--requested-by",
        required=True,
        help="Existing participant authorizing the join",
    )

    task_access = commands.add_parser(
        "task-access-set", help="Set task discoverability and admission policy"
    )
    task_access.add_argument("--task-id", required=True)
    task_access.add_argument("--agent", required=True)
    task_access.add_argument("--join-policy", choices=JOIN_POLICIES, required=True)
    task_access.add_argument("--discovery-summary")

    manifest = commands.add_parser("task-manifest", help="Read a task manifest as a participant")
    manifest.add_argument("--task-id", required=True)
    manifest.add_argument("--agent", required=True)

    leadership = commands.add_parser(
        "task-leadership", help="Read the task leader and scheduling epoch"
    )
    leadership.add_argument("--task-id", required=True)
    leadership.add_argument("--agent", required=True)
    leadership_transfer = commands.add_parser(
        "task-leadership-transfer", help="Transfer task leadership to a participant"
    )
    leadership_transfer.add_argument("--task-id", required=True)
    leadership_transfer.add_argument("--agent", required=True)
    leadership_transfer.add_argument("--target-agent", required=True)

    leader_lease = commands.add_parser(
        "leader-lease-renew",
        help="Renew observation-only liveness for the current Leader epoch",
    )
    leader_lease.add_argument("--task-id", required=True)
    leader_lease.add_argument("--agent", required=True)
    leader_lease.add_argument("--leader-epoch", type=int, required=True)
    leader_lease.add_argument("--lease-seconds", type=int, default=300)

    leader_observation = commands.add_parser(
        "leader-observation",
        help="Read current Leader liveness without changing authority or cursors",
    )
    leader_observation.add_argument("--task-id", required=True)
    leader_observation.add_argument("--agent", required=True)

    escalation_open = commands.add_parser(
        "escalation-open",
        help="Record one deduplicated non-sensitive incident",
    )
    escalation_open.add_argument("--task-id", required=True)
    escalation_open.add_argument("--agent", required=True)
    escalation_open.add_argument("--leader-epoch", type=int, required=True)
    escalation_open.add_argument(
        "--incident-type", choices=ESCALATION_INCIDENT_TYPES, required=True
    )
    escalation_open.add_argument("--incident-key", required=True)
    escalation_open.add_argument("--affected-agent")
    escalation_open.add_argument("--evidence-pointer")

    escalation_resolve = commands.add_parser(
        "escalation-resolve", help="Resolve an incident as the owner or current Leader"
    )
    escalation_resolve.add_argument("--escalation-id", required=True)
    escalation_resolve.add_argument("--agent", required=True)
    escalation_resolve.add_argument(
        "--resolution-code",
        choices=MANUAL_ESCALATION_RESOLUTION_CODES,
        default="resolved",
    )

    escalation_status = commands.add_parser(
        "escalation-status", help="Read one non-sensitive escalation record"
    )
    escalation_status.add_argument("--escalation-id", required=True)
    escalation_status.add_argument("--agent", required=True)

    escalation_list = commands.add_parser(
        "escalations", help="List non-sensitive escalation records for a task"
    )
    escalation_list.add_argument("--task-id", required=True)
    escalation_list.add_argument("--agent", required=True)
    escalation_list.add_argument("--state", choices=ESCALATION_STATES)

    manifest_set = commands.add_parser(
        "task-manifest-set", help="Update task objective, acceptance, worklog, or phase"
    )
    manifest_set.add_argument("--task-id", required=True)
    manifest_set.add_argument("--agent", required=True)
    manifest_set.add_argument("--objective")
    manifest_set.add_argument("--acceptance-criterion", action="append")
    manifest_set.add_argument("--worklog-path")
    manifest_set.add_argument("--phase", choices=("active", "blocked"))

    task_close = commands.add_parser("task-close", help="Close a task as completed or cancelled")
    task_close.add_argument("--task-id", required=True)
    task_close.add_argument("--agent", required=True)
    task_close.add_argument("--phase", choices=("completed", "cancelled"), default="completed")
    task_close.add_argument("--reason")

    task_reopen = commands.add_parser("task-reopen", help="Reopen a non-archived task")
    task_reopen.add_argument("--task-id", required=True)
    task_reopen.add_argument("--agent", required=True)

    task_archive = commands.add_parser("task-archive", help="Archive a closed task permanently")
    task_archive.add_argument("--task-id", required=True)
    task_archive.add_argument("--agent", required=True)

    discover = commands.add_parser(
        "task-discover",
        help="Find explicitly discoverable tasks without reading events",
    )
    discover.add_argument("--agent", required=True)
    discover.add_argument("--query")
    discover.add_argument("--limit", type=int, default=50)

    join_request = commands.add_parser(
        "join-request", help="Request admission to a discoverable task"
    )
    join_request.add_argument("--task-id", required=True)
    join_request.add_argument("--agent", required=True)
    join_request.add_argument("--message", required=True)

    join_requests = commands.add_parser(
        "join-requests", help="List admission requests for a task participant"
    )
    join_requests.add_argument("--task-id", required=True)
    join_requests.add_argument("--agent", required=True)
    join_requests.add_argument(
        "--status", choices=(*JOIN_REQUEST_STATUSES, "all"), default="pending"
    )

    join_status = commands.add_parser(
        "join-request-status",
        help="Read an admission request as requester or participant",
    )
    join_status.add_argument("--request-id", required=True)
    join_status.add_argument("--agent", required=True)

    join_resolve = commands.add_parser(
        "join-request-resolve", help="Approve or deny an admission request"
    )
    join_resolve.add_argument("--request-id", required=True)
    join_resolve.add_argument("--agent", required=True)
    join_resolve.add_argument("--decision", choices=("approve", "deny"), required=True)
    join_resolve.add_argument("--note")

    invite_create = commands.add_parser(
        "invite-create", help="Create a one-time Agent-bound admission invitation"
    )
    invite_create.add_argument("--task-id", required=True)
    invite_create.add_argument("--target-agent", required=True)
    invite_create.add_argument("--agent", required=True)
    invite_create.add_argument("--expires-in-minutes", type=int, default=60)

    invite_list = commands.add_parser("invite-list", help="List invitations for a task participant")
    invite_list.add_argument("--task-id", required=True)
    invite_list.add_argument("--agent", required=True)

    invite_redeem = commands.add_parser(
        "invite-redeem", help="Redeem an Agent-bound admission invitation"
    )
    invite_redeem.add_argument("--token", required=True)
    invite_redeem.add_argument("--agent", required=True)

    invite_revoke = commands.add_parser(
        "invite-revoke", help="Revoke an unused admission invitation"
    )
    invite_revoke.add_argument("--invitation-id", required=True)
    invite_revoke.add_argument("--agent", required=True)

    tasks = commands.add_parser("tasks", help="List tasks visible to an Agent")
    tasks.add_argument("--agent", required=True)

    dashboard = commands.add_parser(
        "dashboard", help="Show a read-only coordination summary for an Agent"
    )
    dashboard.add_argument("--agent", required=True)

    shutdown_status = commands.add_parser(
        "broker-shutdown-status",
        help="Read whether registered Agents have active work that blocks finite Broker exit",
    )
    shutdown_status.add_argument("--agent", action="append", required=True)

    leader_view = commands.add_parser(
        "leader-view",
        help="Derive current-leader request and response state without changing cursors",
    )
    leader_view.add_argument("--task-id", required=True)
    leader_view.add_argument("--agent", required=True)
    leader_view.add_argument("--after", type=int, default=0)
    leader_view.add_argument("--limit", type=int, default=50)
    leader_view.add_argument("--stale-after-seconds", type=int, default=300)

    publish = commands.add_parser("publish", help="Append an event to a task")
    publish.add_argument("--task-id", required=True)
    publish.add_argument("--agent", required=True)
    publish.add_argument("--kind", required=True, choices=EVENT_KINDS)
    publish.add_argument("--summary", required=True)
    publish.add_argument("--details")
    publish.add_argument("--evidence", action="append", default=[])
    publish.add_argument("--reply-to")
    publish.add_argument("--target-agent")

    list_events = commands.add_parser("list", help="List events after an explicit or stored cursor")
    list_events.add_argument("--task-id", required=True)
    list_events.add_argument("--agent", required=True)
    list_events.add_argument("--after", type=int)
    list_events.add_argument("--limit", type=int, default=50)
    list_events.add_argument("--include-own", action="store_true")

    read = commands.add_parser("read", help="Read one event visible to an Agent")
    read.add_argument("--event", required=True, help="Event UUID")
    read.add_argument("--agent", required=True)

    acknowledge = commands.add_parser(
        "ack", help="Acknowledge an event and advance the Agent cursor"
    )
    acknowledge.add_argument("--event", required=True, help="Event UUID")
    acknowledge.add_argument("--agent", required=True)

    wake_claim = commands.add_parser(
        "wake-claim",
        help="Atomically authorize one target Agent wake for a current-leader event",
    )
    wake_claim.add_argument("--task-id", required=True)
    wake_claim.add_argument("--event", required=True, help="Event UUID")
    wake_claim.add_argument("--claimer-agent", required=True)
    wake_claim.add_argument("--adapter-id", required=True)
    wake_claim.add_argument("--attempt-id", required=True, help="Caller-generated UUID")
    wake_claim.add_argument("--lease-seconds", type=int, default=120)
    wake_claim.add_argument("--retry-claim-id", help="Explicit launch_failed claim UUID")

    wake_finish = commands.add_parser(
        "wake-claim-finish",
        help="Record whether an atomically claimed wake was dispatched or failed before launch",
    )
    wake_finish.add_argument("--claim-id", required=True, help="Wake claim UUID")
    wake_finish.add_argument("--claimer-agent", required=True)
    wake_finish.add_argument("--outcome", required=True, choices=("dispatched", "launch_failed"))
    wake_finish.add_argument("--result-code")

    wake_status = commands.add_parser(
        "wake-claim-status",
        help="Read one visible wake claim without acknowledging an event",
    )
    wake_status.add_argument("--claim-id", required=True, help="Wake claim UUID")
    wake_status.add_argument("--agent", required=True)

    work_claim = commands.add_parser(
        "work-claim",
        help="Atomically allocate logical resources to one task participant",
    )
    work_claim.add_argument("--task-id", required=True)
    work_claim.add_argument("--agent", required=True, help="Current Leader Agent")
    work_claim.add_argument("--worker-agent", required=True)
    work_claim.add_argument("--resource", action="append", required=True)
    work_claim.add_argument("--package-id", required=True, help="Caller-generated UUID")
    work_claim.add_argument("--lease-seconds", type=int, default=900)
    work_claim.add_argument("--takeover-package-id")

    work_finish = commands.add_parser(
        "work-claim-finish",
        help="Complete, fail, or release one atomic work allocation",
    )
    work_finish.add_argument("--package-id", required=True)
    work_finish.add_argument("--agent", required=True)
    work_finish.add_argument(
        "--outcome", required=True, choices=("completed", "failed", "released")
    )
    work_finish.add_argument("--result-code")

    work_status = commands.add_parser(
        "work-claim-status", help="Read one work allocation without changing it"
    )
    work_status.add_argument("--package-id", required=True)
    work_status.add_argument("--agent", required=True)

    work_list = commands.add_parser(
        "work-claims", help="List task work allocations without changing them"
    )
    work_list.add_argument("--task-id", required=True)
    work_list.add_argument("--agent", required=True)
    work_list.add_argument("--state", choices=WORK_CLAIM_STATES)

    status = commands.add_parser("status", help="Show task participants and unread state")
    status.add_argument("--task-id", required=True)
    status.add_argument("--agent", required=True)

    commands.add_parser("health", help="Run SQLite integrity and schema checks")

    snapshot = commands.add_parser("snapshot", help="Create a consistent SQLite backup")
    snapshot.add_argument("--output", required=True, type=Path)

    restore = commands.add_parser(
        "restore", help="Restore a validated snapshot and preserve the current database"
    )
    restore.add_argument("--snapshot", required=True, type=Path)
    restore.add_argument("--rollback-output", required=True, type=Path)
    return parser


def run(args: argparse.Namespace) -> Any:
    bridge = ConversationBridge(args.db)
    if args.command == "init":
        return bridge.initialize()
    if args.command == "task-create":
        return bridge.create_task(
            args.task_id,
            args.title,
            args.agent,
            args.join_policy,
            args.discovery_summary,
            args.objective,
            args.acceptance_criterion,
            args.worklog_path,
        )
    if args.command == "task-join":
        return bridge.join_task(args.task_id, args.agent, args.requested_by)
    if args.command == "task-access-set":
        return bridge.set_task_access(
            args.task_id, args.agent, args.join_policy, args.discovery_summary
        )
    if args.command == "task-manifest":
        return bridge.get_task_manifest(args.task_id, args.agent)
    if args.command == "task-leadership":
        return bridge.get_task_leadership(args.task_id, args.agent)
    if args.command == "task-leadership-transfer":
        return bridge.transfer_task_leadership(args.task_id, args.agent, args.target_agent)
    if args.command == "leader-lease-renew":
        return bridge.renew_leader_lease(
            args.task_id, args.agent, args.leader_epoch, args.lease_seconds
        )
    if args.command == "leader-observation":
        return bridge.get_leader_observation(args.task_id, args.agent)
    if args.command == "escalation-open":
        return bridge.open_escalation(
            args.task_id,
            args.agent,
            args.leader_epoch,
            args.incident_type,
            args.incident_key,
            args.affected_agent,
            args.evidence_pointer,
        )
    if args.command == "escalation-resolve":
        return bridge.resolve_escalation(args.escalation_id, args.agent, args.resolution_code)
    if args.command == "escalation-status":
        return bridge.get_escalation(args.escalation_id, args.agent)
    if args.command == "escalations":
        return {"escalations": bridge.list_escalations(args.task_id, args.agent, args.state)}
    if args.command == "task-manifest-set":
        return bridge.set_task_manifest(
            args.task_id,
            args.agent,
            args.objective,
            args.acceptance_criterion,
            args.worklog_path,
            args.phase,
        )
    if args.command == "task-close":
        return bridge.close_task(args.task_id, args.agent, args.phase, args.reason)
    if args.command == "task-reopen":
        return bridge.reopen_task(args.task_id, args.agent)
    if args.command == "task-archive":
        return bridge.archive_task(args.task_id, args.agent)
    if args.command == "task-discover":
        return {"tasks": bridge.discover_tasks(args.agent, args.query, args.limit)}
    if args.command == "join-request":
        return bridge.create_join_request(args.task_id, args.agent, args.message)
    if args.command == "join-requests":
        return {"requests": bridge.list_join_requests(args.task_id, args.agent, args.status)}
    if args.command == "join-request-status":
        return bridge.get_join_request(args.request_id, args.agent)
    if args.command == "join-request-resolve":
        return bridge.resolve_join_request(args.request_id, args.agent, args.decision, args.note)
    if args.command == "invite-create":
        return bridge.create_invitation(
            args.task_id,
            args.target_agent,
            args.agent,
            args.expires_in_minutes,
        )
    if args.command == "invite-list":
        return {"invitations": bridge.list_invitations(args.task_id, args.agent)}
    if args.command == "invite-redeem":
        return bridge.redeem_invitation(args.token, args.agent)
    if args.command == "invite-revoke":
        return bridge.revoke_invitation(args.invitation_id, args.agent)
    if args.command == "tasks":
        return {"tasks": bridge.list_tasks(args.agent)}
    if args.command == "dashboard":
        return bridge.dashboard(args.agent)
    if args.command == "broker-shutdown-status":
        return bridge.broker_shutdown_status(args.agent)
    if args.command == "leader-view":
        return bridge.leader_view(
            args.task_id,
            args.agent,
            args.after,
            args.limit,
            args.stale_after_seconds,
        )
    if args.command == "publish":
        return bridge.publish(
            task_id=args.task_id,
            source_agent=args.agent,
            kind=args.kind,
            summary=args.summary,
            details=args.details,
            evidence=args.evidence,
            reply_to_uid=args.reply_to,
            target_agent=args.target_agent,
        )
    if args.command == "list":
        return {
            "events": bridge.list_events(
                task_id=args.task_id,
                agent_id=args.agent,
                after_event_id=args.after,
                limit=args.limit,
                include_own=args.include_own,
            )
        }
    if args.command == "read":
        return bridge.read_event(args.event, args.agent)
    if args.command == "ack":
        return bridge.acknowledge(args.event, args.agent)
    if args.command == "wake-claim":
        return bridge.claim_wake(
            args.task_id,
            args.event,
            args.claimer_agent,
            args.adapter_id,
            args.attempt_id,
            args.lease_seconds,
            args.retry_claim_id,
        )
    if args.command == "wake-claim-finish":
        return bridge.finish_wake_claim(
            args.claim_id, args.claimer_agent, args.outcome, args.result_code
        )
    if args.command == "wake-claim-status":
        return bridge.get_wake_claim(args.claim_id, args.agent)
    if args.command == "work-claim":
        return bridge.claim_work(
            args.task_id,
            args.agent,
            args.worker_agent,
            args.resource,
            args.package_id,
            args.lease_seconds,
            args.takeover_package_id,
        )
    if args.command == "work-claim-finish":
        return bridge.finish_work_claim(args.package_id, args.agent, args.outcome, args.result_code)
    if args.command == "work-claim-status":
        return bridge.get_work_claim(args.package_id, args.agent)
    if args.command == "work-claims":
        return {"claims": bridge.list_work_claims(args.task_id, args.agent, args.state)}
    if args.command == "status":
        return bridge.status(args.task_id, args.agent)
    if args.command == "health":
        return bridge.health()
    if args.command == "snapshot":
        return bridge.snapshot(args.output)
    if args.command == "restore":
        return bridge.restore(args.snapshot, args.rollback_output)
    raise BridgeError("invalid_command", f"unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    try:
        arguments = build_parser().parse_args(argv)
        _emit(run(arguments))
        return 0
    except BridgeError as exc:
        _emit({"code": exc.code, "message": str(exc)}, ok=False, stream=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        _emit({"code": "database_error", "message": str(exc)}, ok=False, stream=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
