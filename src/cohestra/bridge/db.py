# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

SCHEMA_VERSION = 7
LEGACY_SCHEMA_VERSIONS = (1, 2, 3, 4, 5, 6)
EVENT_KINDS = ("update", "handoff", "request", "response")
WAKE_CLAIMABLE_KINDS = ("request", "handoff")
WAKE_CLAIM_STATES = (
    "claimed",
    "dispatched",
    "launch_failed",
    "expired_unknown",
    "relinquished",
)
WORK_CLAIM_STATES = (
    "claimed",
    "completed",
    "failed",
    "released",
    "expired_unknown",
)
LEADER_OBSERVATION_STATES = ("healthy", "leader_unresponsive", "not_renewed")
ESCALATION_STATES = ("open", "resolved")
ESCALATION_INCIDENT_TYPES = (
    "leader_unresponsive",
    "wake_claim_failed",
    "wake_claim_expired",
    "work_claim_failed",
    "work_claim_expired",
    "response_missing",
    "acknowledgement_missing",
    "join_approval_pending",
)
ESCALATION_RESOLUTION_CODES = (
    "resolved",
    "false_positive",
    "superseded",
    "leadership_transferred",
    "task_closed",
)
MANUAL_ESCALATION_RESOLUTION_CODES = (
    "resolved",
    "false_positive",
    "superseded",
)
ESCALATION_ACTION_BY_TYPE = {
    "leader_unresponsive": "inspect_leader",
    "wake_claim_failed": "inspect_wake_claim",
    "wake_claim_expired": "inspect_wake_claim",
    "work_claim_failed": "inspect_work_claim",
    "work_claim_expired": "inspect_work_claim",
    "response_missing": "review_response",
    "acknowledgement_missing": "review_acknowledgement",
    "join_approval_pending": "review_join_request",
}
ESCALATION_KEY_PREFIX_BY_TYPE = {
    "leader_unresponsive": "leader_epoch",
    "wake_claim_failed": "wake_claim",
    "wake_claim_expired": "wake_claim",
    "work_claim_failed": "work_package",
    "work_claim_expired": "work_package",
    "response_missing": "event",
    "acknowledgement_missing": "event",
    "join_approval_pending": "join_request",
}
JOIN_POLICIES = ("private", "request")
JOIN_REQUEST_STATUSES = ("pending", "approved", "denied")
TASK_PHASES = ("active", "blocked", "completed", "cancelled", "archived")
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,127}$")
AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ADAPTER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
RESULT_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
RESOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,255}$")
EVIDENCE_POINTER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,511}$")

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open', 'closed'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS participants (
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        agent_id TEXT NOT NULL,
        joined_at TEXT NOT NULL,
        last_read_event_id INTEGER NOT NULL DEFAULT 0,
        admission_method TEXT NOT NULL DEFAULT 'legacy',
        authorized_by TEXT,
        admission_ref TEXT,
        PRIMARY KEY (task_id, agent_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_uid TEXT NOT NULL UNIQUE,
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        source_agent TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('update', 'handoff', 'request', 'response')),
        summary TEXT NOT NULL,
        details TEXT,
        reply_to_uid TEXT REFERENCES events(event_uid),
        evidence_json TEXT NOT NULL,
        target_agent TEXT,
        leader_epoch INTEGER,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS acknowledgements (
        event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
        agent_id TEXT NOT NULL,
        acknowledged_at TEXT NOT NULL,
        PRIMARY KEY (event_id, agent_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_task_event ON events(task_id, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_task_source ON events(task_id, source_agent, event_id)",
)

V2_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS task_access (
        task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
        join_policy TEXT NOT NULL CHECK (join_policy IN ('private', 'request')),
        discovery_summary TEXT,
        updated_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS join_requests (
        request_uid TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        agent_id TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'denied')),
        created_at TEXT NOT NULL,
        resolved_by TEXT,
        resolved_at TEXT,
        resolution_note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invitations (
        invitation_uid TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        target_agent_id TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        consumed_at TEXT,
        consumed_by TEXT,
        revoked_at TEXT,
        revoked_by TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_join_requests_pending ON join_requests(task_id, agent_id) WHERE status = 'pending'",
    "CREATE INDEX IF NOT EXISTS idx_join_requests_task_status ON join_requests(task_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_invitations_task_target ON invitations(task_id, target_agent_id, created_at)",
)

V3_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS task_manifest (
        task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
        objective TEXT NOT NULL,
        acceptance_criteria_json TEXT NOT NULL,
        worklog_path TEXT,
        owner_agent TEXT NOT NULL,
        phase TEXT NOT NULL CHECK (phase IN ('active', 'blocked', 'completed', 'cancelled', 'archived')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        closed_at TEXT,
        closed_by TEXT,
        closed_reason TEXT,
        archived_at TEXT,
        archived_by TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_manifest_phase ON task_manifest(phase, updated_at)",
)

V4_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS task_leadership (
        task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
        leader_agent TEXT NOT NULL,
        epoch INTEGER NOT NULL CHECK (epoch >= 1),
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_task_target_event ON events(task_id, target_agent, event_id)",
)

V5_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS wake_claims (
        claim_uid TEXT PRIMARY KEY,
        attempt_uid TEXT NOT NULL UNIQUE,
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        event_uid TEXT NOT NULL REFERENCES events(event_uid) ON DELETE CASCADE,
        target_agent TEXT NOT NULL,
        claimer_agent TEXT NOT NULL,
        adapter_id TEXT NOT NULL,
        leader_agent TEXT NOT NULL,
        leader_epoch INTEGER NOT NULL CHECK (leader_epoch >= 1),
        state TEXT NOT NULL CHECK (state IN ('claimed', 'dispatched', 'launch_failed', 'expired_unknown', 'relinquished')),
        claimed_at TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL,
        finalized_at TEXT,
        result_code TEXT,
        supersedes_claim_uid TEXT REFERENCES wake_claims(claim_uid)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wake_claims_event_history ON wake_claims(event_uid, claimed_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_wake_claim_live ON wake_claims(event_uid) WHERE state = 'claimed'",
)

V6_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS work_claims (
        package_uid TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        worker_agent TEXT NOT NULL,
        leader_agent TEXT NOT NULL,
        leader_epoch INTEGER NOT NULL CHECK (leader_epoch >= 1),
        state TEXT NOT NULL CHECK (state IN ('claimed', 'completed', 'failed', 'released', 'expired_unknown')),
        claimed_at TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL,
        finalized_at TEXT,
        result_code TEXT,
        supersedes_package_uid TEXT,
        PRIMARY KEY (package_uid, resource_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_work_claims_package ON work_claims(package_uid, resource_id)",
    "CREATE INDEX IF NOT EXISTS idx_work_claims_task_state ON work_claims(task_id, state, claimed_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claim_live_resource ON work_claims(task_id, resource_id) WHERE state = 'claimed'",
)

V7_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS leader_leases (
        task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
        leader_agent TEXT NOT NULL,
        leader_epoch INTEGER NOT NULL CHECK (leader_epoch >= 1),
        renewed_at TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_leader_leases_expiry ON leader_leases(lease_expires_at)",
    """
    CREATE TABLE IF NOT EXISTS escalations (
        escalation_uid TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        incident_type TEXT NOT NULL CHECK (incident_type IN (
            'leader_unresponsive', 'wake_claim_failed', 'wake_claim_expired',
            'work_claim_failed', 'work_claim_expired', 'response_missing',
            'acknowledgement_missing', 'join_approval_pending'
        )),
        incident_key TEXT NOT NULL,
        leader_epoch INTEGER NOT NULL CHECK (leader_epoch >= 1),
        reported_by TEXT NOT NULL,
        affected_agent TEXT,
        action_code TEXT NOT NULL CHECK (action_code IN (
            'inspect_leader', 'inspect_wake_claim', 'inspect_work_claim',
            'review_response', 'review_acknowledgement', 'review_join_request'
        )),
        evidence_pointer TEXT,
        state TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
        opened_at TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by TEXT,
        resolution_code TEXT CHECK (resolution_code IS NULL OR resolution_code IN (
            'resolved', 'false_positive', 'superseded',
            'leadership_transferred', 'task_closed'
        )),
        CHECK (
            (state = 'open' AND resolved_at IS NULL AND resolved_by IS NULL AND resolution_code IS NULL)
            OR
            (state = 'resolved' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL AND resolution_code IS NOT NULL)
        ),
        UNIQUE (task_id, incident_key, leader_epoch)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_escalations_task_state ON escalations(task_id, state, opened_at)",
)


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_task_id(task_id: str) -> str:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise BridgeError("invalid_task_id", "task_id must be 1-128 safe identifier characters")
    return task_id


def _validate_agent_id(agent_id: str) -> str:
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise BridgeError(
            "invalid_agent_id",
            "agent_id must use lowercase letters, digits, and hyphens",
        )
    return agent_id


def _validate_adapter_id(adapter_id: str) -> str:
    if not ADAPTER_ID_PATTERN.fullmatch(adapter_id):
        raise BridgeError(
            "invalid_adapter_id",
            "adapter_id must use lowercase letters, digits, dots, underscores, and hyphens",
        )
    return adapter_id


def _validate_result_code(result_code: str | None) -> str | None:
    if result_code is None:
        return None
    if not RESULT_CODE_PATTERN.fullmatch(result_code):
        raise BridgeError(
            "invalid_result_code",
            "result_code must be a stable identifier of at most 64 characters",
        )
    return result_code


def _validate_resource_id(resource_id: str) -> str:
    if not RESOURCE_ID_PATTERN.fullmatch(resource_id):
        raise BridgeError(
            "invalid_resource_id",
            "resource_id must be a lowercase logical identifier, not a path",
        )
    segments = resource_id.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise BridgeError(
            "invalid_resource_id",
            "resource_id must not contain empty, dot, or parent segments",
        )
    return resource_id


def _validate_incident_key(incident_type: str, incident_key: str, leader_epoch: int) -> str:
    if incident_type not in ESCALATION_INCIDENT_TYPES:
        raise BridgeError(
            "invalid_incident_type",
            f"incident_type must be one of: {', '.join(ESCALATION_INCIDENT_TYPES)}",
        )
    incident_key = _validate_text(incident_key, "incident_key", 96)
    expected_prefix = ESCALATION_KEY_PREFIX_BY_TYPE[incident_type]
    prefix, separator, identifier = incident_key.partition(":")
    if separator != ":" or prefix != expected_prefix or not identifier:
        raise BridgeError(
            "invalid_incident_key",
            f"incident_key for {incident_type} must use {expected_prefix}:<stable-id>",
        )
    if expected_prefix == "leader_epoch":
        if not identifier.isdecimal() or int(identifier) != leader_epoch:
            raise BridgeError(
                "invalid_incident_key",
                "leader_epoch incident_key must match the supplied leader epoch",
            )
        return f"{prefix}:{int(identifier)}"
    normalized = _validate_uuid(identifier, "incident_key")
    if identifier != normalized:
        raise BridgeError("invalid_incident_key", "incident_key UUID must use canonical form")
    return f"{prefix}:{normalized}"


def _validate_evidence_pointer(value: str | None) -> str | None:
    if value is None:
        return None
    value = _validate_text(value, "evidence_pointer", 512)
    if not EVIDENCE_POINTER_PATTERN.fullmatch(value):
        raise BridgeError(
            "invalid_evidence_pointer",
            "evidence_pointer must be a relative logical identifier",
        )
    if re.match(r"^[A-Za-z]:", value):
        raise BridgeError(
            "invalid_evidence_pointer", "evidence_pointer must not be an absolute path"
        )
    if any(segment in ("", ".", "..") for segment in value.split("/")):
        raise BridgeError(
            "invalid_evidence_pointer",
            "evidence_pointer must not contain empty, dot, or parent segments",
        )
    return value


def _validate_text(value: str, field: str, maximum: int) -> str:
    value = value.strip()
    if not value:
        raise BridgeError(f"invalid_{field}", f"{field} must not be empty")
    if len(value) > maximum:
        raise BridgeError(f"invalid_{field}", f"{field} exceeds {maximum} characters")
    return value


def _validate_optional_text(value: str | None, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _validate_text(value, field, maximum)


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BridgeError("invalid_timestamp", f"invalid UTC timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise BridgeError("invalid_timestamp", f"timestamp has no timezone: {value}")
    return parsed.astimezone(UTC)


def _validate_uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise BridgeError(f"invalid_{field}", f"{field} must be a UUID") from exc


def _validate_criteria(criteria: Sequence[str] | None) -> list[str]:
    if criteria is None:
        return []
    values = [_validate_text(item, "acceptance_criterion", 1000) for item in criteria]
    if len(values) > 32:
        raise BridgeError(
            "invalid_acceptance_criteria", "at most 32 acceptance criteria are allowed"
        )
    return values


class ConversationBridge:
    def __init__(self, database: Path | str, timeout_seconds: float = 15.0):
        self.database = Path(database).expanduser().resolve()
        self.timeout_seconds = timeout_seconds

    def _connect(self, require_exists: bool = True) -> sqlite3.Connection:
        if require_exists and not self.database.is_file():
            raise BridgeError("not_initialized", f"bridge database does not exist: {self.database}")
        if not require_exists:
            self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.database,
            timeout=self.timeout_seconds,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {int(self.timeout_seconds * 1000)}")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA journal_mode = WAL")
        except Exception:
            connection.close()
            raise
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> dict[str, Any]:
        connection = self._connect(require_exists=False)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            current = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            current_version = int(current["value"]) if current else None
            if current_version not in (None, *LEGACY_SCHEMA_VERSIONS, SCHEMA_VERSION):
                raise BridgeError(
                    "unsupported_schema",
                    f"database schema {current_version} is not supported by this version",
                )
            self._ensure_v2_schema(connection)
            self._ensure_v3_schema(connection)
            self._ensure_v4_schema(connection)
            self._ensure_v5_schema(connection)
            self._ensure_v6_schema(connection)
            self._ensure_v7_schema(connection)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {
            "database": str(self.database),
            "schema_version": SCHEMA_VERSION,
            "migrated_from": current_version,
        }

    @staticmethod
    def _ensure_v2_schema(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(participants)")}
        # v1 snapshots predate admission provenance. ALTER is intentionally
        # additive so restoring an old snapshot never requires rebuilding data.
        additions = {
            "admission_method": "TEXT NOT NULL DEFAULT 'legacy'",
            "authorized_by": "TEXT",
            "admission_ref": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE participants ADD COLUMN {name} {declaration}")
        for statement in V2_SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            """
            INSERT OR IGNORE INTO task_access(
                task_id, join_policy, discovery_summary, updated_by, updated_at
            )
            SELECT task_id, 'private', NULL, created_by, created_at FROM tasks
            """
        )

    @staticmethod
    def _ensure_v3_schema(connection: sqlite3.Connection) -> None:
        for statement in V3_SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            """
            INSERT OR IGNORE INTO task_manifest(
                task_id, objective, acceptance_criteria_json, worklog_path,
                owner_agent, phase, created_at, updated_at
            )
            SELECT task_id, title, '[]', NULL, created_by, 'active', created_at, created_at
            FROM tasks
            """
        )

    @staticmethod
    def _ensure_v4_schema(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
        # Event routing is additive so v1-v3 snapshots retain their broadcast history.
        if "target_agent" not in columns:
            connection.execute("ALTER TABLE events ADD COLUMN target_agent TEXT")
        if "leader_epoch" not in columns:
            connection.execute("ALTER TABLE events ADD COLUMN leader_epoch INTEGER")
        for statement in V4_SCHEMA_STATEMENTS:
            connection.execute(statement)
        # The v3 owner remains the initial leader, preserving prior task authority.
        connection.execute(
            """
            INSERT OR IGNORE INTO task_leadership(task_id, leader_agent, epoch, updated_at, updated_by)
            SELECT task_id, owner_agent, 1, updated_at, owner_agent FROM task_manifest
            """
        )

    @staticmethod
    def _ensure_v5_schema(connection: sqlite3.Connection) -> None:
        for statement in V5_SCHEMA_STATEMENTS:
            connection.execute(statement)

    @staticmethod
    def _ensure_v6_schema(connection: sqlite3.Connection) -> None:
        for statement in V6_SCHEMA_STATEMENTS:
            connection.execute(statement)

    @staticmethod
    def _ensure_v7_schema(connection: sqlite3.Connection) -> None:
        for statement in V7_SCHEMA_STATEMENTS:
            connection.execute(statement)

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        try:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise BridgeError("not_initialized", "bridge schema is missing") from exc
        if not row:
            raise BridgeError("not_initialized", "bridge schema version is missing")
        try:
            return int(row["value"])
        except ValueError as exc:
            raise BridgeError(
                "unsupported_schema", f"invalid schema version: {row['value']}"
            ) from exc

    def _require_schema(self, connection: sqlite3.Connection) -> None:
        version = self._schema_version(connection)
        if version != SCHEMA_VERSION:
            raise BridgeError(
                "unsupported_schema",
                f"schema version {version} requires init migration to {SCHEMA_VERSION}",
            )

    @staticmethod
    def _require_supported_schema(connection: sqlite3.Connection) -> int:
        version = ConversationBridge._schema_version(connection)
        if version not in (*LEGACY_SCHEMA_VERSIONS, SCHEMA_VERSION):
            raise BridgeError("unsupported_schema", f"unsupported schema version: {version}")
        return version

    @staticmethod
    def _require_task(connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            raise BridgeError("task_not_found", f"task does not exist: {task_id}")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _require_member(connection: sqlite3.Connection, task_id: str, agent_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM participants WHERE task_id = ? AND agent_id = ?",
            (task_id, agent_id),
        ).fetchone()
        if not row:
            raise BridgeError(
                "not_a_participant",
                f"agent {agent_id} is not a participant of {task_id}",
            )
        return cast(sqlite3.Row, row)

    @staticmethod
    def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["evidence"] = json.loads(value.pop("evidence_json"))
        return value

    @staticmethod
    def _request_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _invitation_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value.pop("token_hash", None)
        return value

    def create_task(
        self,
        task_id: str,
        title: str,
        agent_id: str,
        join_policy: str = "private",
        discovery_summary: str | None = None,
        objective: str | None = None,
        acceptance_criteria: Sequence[str] | None = None,
        worklog_path: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        title = _validate_text(title, "title", 240)
        if join_policy not in JOIN_POLICIES:
            raise BridgeError(
                "invalid_join_policy",
                f"join_policy must be one of: {', '.join(JOIN_POLICIES)}",
            )
        discovery_summary = _validate_optional_text(discovery_summary, "discovery_summary", 1000)
        objective = _validate_text(objective or title, "objective", 4000)
        criteria = _validate_criteria(acceptance_criteria)
        worklog_path = _validate_optional_text(worklog_path, "worklog_path", 2048)
        created_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            try:
                connection.execute(
                    "INSERT INTO tasks(task_id, title, created_by, created_at, status) VALUES(?, ?, ?, ?, 'open')",
                    (task_id, title, agent_id, created_at),
                )
            except sqlite3.IntegrityError as exc:
                raise BridgeError("task_exists", f"task already exists: {task_id}") from exc
            connection.execute(
                """
                INSERT INTO participants(
                    task_id, agent_id, joined_at, admission_method,
                    authorized_by, admission_ref
                ) VALUES(?, ?, ?, 'creator', ?, NULL)
                """,
                (task_id, agent_id, created_at, agent_id),
            )
            connection.execute(
                """
                INSERT INTO task_access(
                    task_id, join_policy, discovery_summary, updated_by, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (task_id, join_policy, discovery_summary, agent_id, created_at),
            )
            connection.execute(
                """
                INSERT INTO task_manifest(
                    task_id, objective, acceptance_criteria_json, worklog_path,
                    owner_agent, phase, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    task_id,
                    objective,
                    json.dumps(criteria, ensure_ascii=False, separators=(",", ":")),
                    worklog_path,
                    agent_id,
                    created_at,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO task_leadership(task_id, leader_agent, epoch, updated_at, updated_by)
                VALUES(?, ?, 1, ?, ?)
                """,
                (task_id, agent_id, created_at, agent_id),
            )
        return {
            "task_id": task_id,
            "title": title,
            "created_by": agent_id,
            "created_at": created_at,
            "status": "open",
            "join_policy": join_policy,
            "discovery_summary": discovery_summary,
            "objective": objective,
            "acceptance_criteria": criteria,
            "worklog_path": worklog_path,
            "owner_agent": agent_id,
            "phase": "active",
            "leader_agent": agent_id,
            "leader_epoch": 1,
        }

    @staticmethod
    def _manifest_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        raw = value.pop("acceptance_criteria_json", "[]")
        try:
            value["acceptance_criteria"] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BridgeError("invalid_manifest", "acceptance criteria JSON is invalid") from exc
        return value

    @staticmethod
    def _require_owner(connection: sqlite3.Connection, task_id: str, agent_id: str) -> sqlite3.Row:
        manifest = connection.execute(
            "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not manifest:
            raise BridgeError("manifest_not_found", f"task manifest does not exist: {task_id}")
        if manifest["owner_agent"] != agent_id:
            raise BridgeError(
                "not_task_owner",
                f"agent {agent_id} is not the owner of {task_id}",
            )
        return cast(sqlite3.Row, manifest)

    @staticmethod
    def _require_leadership(connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM task_leadership WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not row:
            raise BridgeError("leadership_not_found", f"task leadership does not exist: {task_id}")
        return cast(sqlite3.Row, row)

    def get_task_leadership(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            self._require_member(connection, task_id, agent_id)
            return dict(self._require_leadership(connection, task_id))
        finally:
            connection.close()

    def transfer_task_leadership(
        self, task_id: str, agent_id: str, target_agent: str
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        target_agent = _validate_agent_id(target_agent)
        updated_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            self._require_member(connection, task_id, agent_id)
            self._require_member(connection, task_id, target_agent)
            leadership = self._require_leadership(connection, task_id)
            owner_agent = connection.execute(
                "SELECT owner_agent FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()["owner_agent"]
            if agent_id not in (leadership["leader_agent"], owner_agent):
                raise BridgeError(
                    "not_task_leader",
                    f"agent {agent_id} is neither the leader nor owner of {task_id}",
                )
            if target_agent == leadership["leader_agent"]:
                return dict(leadership)
            connection.execute(
                "UPDATE task_leadership SET leader_agent = ?, epoch = epoch + 1, updated_at = ?, updated_by = ? WHERE task_id = ?",
                (target_agent, updated_at, agent_id, task_id),
            )
            # A lease is evidence for one exact leader epoch. Carrying it across
            # transfer would make the successor appear healthy without renewing.
            connection.execute("DELETE FROM leader_leases WHERE task_id = ?", (task_id,))
            return dict(self._require_leadership(connection, task_id))

    def renew_leader_lease(
        self,
        task_id: str,
        agent_id: str,
        leader_epoch: int,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if not isinstance(leader_epoch, int) or isinstance(leader_epoch, bool) or leader_epoch < 1:
            raise BridgeError("invalid_leader_epoch", "leader_epoch must be at least 1")
        if (
            not isinstance(lease_seconds, int)
            or isinstance(lease_seconds, bool)
            or not 1 <= lease_seconds <= 3600
        ):
            raise BridgeError("invalid_lease_seconds", "lease_seconds must be between 1 and 3600")
        renewed_at = utc_now()
        lease_expires_at = (
            (_parse_utc(renewed_at) + timedelta(seconds=lease_seconds))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            leadership = self._require_leadership(connection, task_id)
            # Check the epoch first so an old Leader racing a transfer receives
            # a stable fencing error rather than an authority-dependent result.
            if leader_epoch != leadership["epoch"]:
                raise BridgeError(
                    "stale_leader_epoch",
                    "leader_epoch does not match current leadership",
                )
            if agent_id != leadership["leader_agent"]:
                raise BridgeError(
                    "not_task_leader",
                    f"agent {agent_id} is not the current task leader",
                )
            if task["status"] != "open":
                raise BridgeError("task_not_open", f"task is closed: {task_id}")
            existing = connection.execute(
                "SELECT leader_agent, leader_epoch FROM leader_leases WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if existing and (
                existing["leader_agent"] != agent_id or existing["leader_epoch"] != leader_epoch
            ):
                raise BridgeError(
                    "stale_leader_epoch", "stored lease belongs to another leader epoch"
                )
            connection.execute(
                """
                INSERT INTO leader_leases(
                    task_id, leader_agent, leader_epoch, renewed_at, lease_expires_at
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    renewed_at = excluded.renewed_at,
                    lease_expires_at = excluded.lease_expires_at
                """,
                (task_id, agent_id, leader_epoch, renewed_at, lease_expires_at),
            )
            row = connection.execute(
                "SELECT * FROM leader_leases WHERE task_id = ?", (task_id,)
            ).fetchone()
        return {**dict(row), "state": "healthy"}

    def get_leader_observation(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        generated_at = utc_now()
        connection = self._connect()
        try:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            leadership = self._require_leadership(connection, task_id)
            lease = connection.execute(
                "SELECT * FROM leader_leases WHERE task_id = ?", (task_id,)
            ).fetchone()
            state = "not_renewed"
            renewed_at = None
            lease_expires_at = None
            if (
                task["status"] == "open"
                and lease
                and lease["leader_agent"] == leadership["leader_agent"]
                and lease["leader_epoch"] == leadership["epoch"]
            ):
                renewed_at = lease["renewed_at"]
                lease_expires_at = lease["lease_expires_at"]
                state = (
                    "leader_unresponsive"
                    if _parse_utc(lease_expires_at) <= _parse_utc(generated_at)
                    else "healthy"
                )
            return {
                "task_id": task_id,
                "leader_agent": leadership["leader_agent"],
                "leader_epoch": leadership["epoch"],
                "state": state,
                "renewed_at": renewed_at,
                "lease_expires_at": lease_expires_at,
                "generated_at": generated_at,
            }
        finally:
            connection.close()

    @staticmethod
    def _escalation_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def open_escalation(
        self,
        task_id: str,
        agent_id: str,
        leader_epoch: int,
        incident_type: str,
        incident_key: str,
        affected_agent: str | None = None,
        evidence_pointer: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if not isinstance(leader_epoch, int) or isinstance(leader_epoch, bool) or leader_epoch < 1:
            raise BridgeError("invalid_leader_epoch", "leader_epoch must be at least 1")
        incident_key = _validate_incident_key(incident_type, incident_key, leader_epoch)
        affected_agent = None if affected_agent is None else _validate_agent_id(affected_agent)
        evidence_pointer = _validate_evidence_pointer(evidence_pointer)
        escalation_uid = str(uuid4())
        opened_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            if affected_agent is not None:
                self._require_member(connection, task_id, affected_agent)
            leadership = self._require_leadership(connection, task_id)
            if leader_epoch != leadership["epoch"]:
                raise BridgeError(
                    "stale_leader_epoch",
                    "leader_epoch does not match current leadership",
                )
            if task["status"] != "open":
                raise BridgeError("task_not_open", f"task is closed: {task_id}")
            # The database, not an application precheck, decides which concurrent
            # reporter owns the one notification opportunity for this incident.
            cursor = connection.execute(
                """
                INSERT INTO escalations(
                    escalation_uid, task_id, incident_type, incident_key,
                    leader_epoch, reported_by, affected_agent, action_code,
                    evidence_pointer, state, opened_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                ON CONFLICT(task_id, incident_key, leader_epoch) DO NOTHING
                """,
                (
                    escalation_uid,
                    task_id,
                    incident_type,
                    incident_key,
                    leader_epoch,
                    agent_id,
                    affected_agent,
                    ESCALATION_ACTION_BY_TYPE[incident_type],
                    evidence_pointer,
                    opened_at,
                ),
            )
            should_notify = cursor.rowcount == 1
            row = connection.execute(
                """
                SELECT * FROM escalations
                WHERE task_id = ? AND incident_key = ? AND leader_epoch = ?
                """,
                (task_id, incident_key, leader_epoch),
            ).fetchone()
        return {**self._escalation_dict(row), "should_notify": should_notify}

    def resolve_escalation(
        self,
        escalation_uid: str,
        agent_id: str,
        resolution_code: str = "resolved",
    ) -> dict[str, Any]:
        escalation_uid = _validate_uuid(escalation_uid, "escalation_id")
        agent_id = _validate_agent_id(agent_id)
        if resolution_code not in MANUAL_ESCALATION_RESOLUTION_CODES:
            raise BridgeError(
                "invalid_resolution_code",
                f"resolution_code must be one of: {', '.join(MANUAL_ESCALATION_RESOLUTION_CODES)}",
            )
        resolved_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM escalations WHERE escalation_uid = ?",
                (escalation_uid,),
            ).fetchone()
            if not row:
                raise BridgeError("escalation_not_found", "escalation record does not exist")
            task_id = row["task_id"]
            self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            leadership = self._require_leadership(connection, task_id)
            owner_agent = connection.execute(
                "SELECT owner_agent FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()["owner_agent"]
            if agent_id not in (owner_agent, leadership["leader_agent"]):
                raise BridgeError(
                    "not_task_leader",
                    f"agent {agent_id} is neither the current leader nor owner of {task_id}",
                )
            if row["state"] == "open":
                connection.execute(
                    """
                    UPDATE escalations
                    SET state = 'resolved', resolved_at = ?, resolved_by = ?,
                        resolution_code = ?
                    WHERE escalation_uid = ? AND state = 'open'
                    """,
                    (resolved_at, agent_id, resolution_code, escalation_uid),
                )
            row = connection.execute(
                "SELECT * FROM escalations WHERE escalation_uid = ?",
                (escalation_uid,),
            ).fetchone()
        return self._escalation_dict(row)

    def get_escalation(self, escalation_uid: str, agent_id: str) -> dict[str, Any]:
        escalation_uid = _validate_uuid(escalation_uid, "escalation_id")
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM escalations WHERE escalation_uid = ?",
                (escalation_uid,),
            ).fetchone()
            if not row:
                raise BridgeError("escalation_not_found", "escalation record does not exist")
            self._require_member(connection, row["task_id"], agent_id)
            return self._escalation_dict(row)
        finally:
            connection.close()

    def list_escalations(
        self, task_id: str, agent_id: str, state: str | None = None
    ) -> list[dict[str, Any]]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if state is not None and state not in ESCALATION_STATES:
            raise BridgeError(
                "invalid_escalation_state",
                f"state must be one of: {', '.join(ESCALATION_STATES)}",
            )
        connection = self._connect()
        try:
            self._require_schema(connection)
            self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            sql = "SELECT * FROM escalations WHERE task_id = ?"
            parameters: list[Any] = [task_id]
            if state is not None:
                sql += " AND state = ?"
                parameters.append(state)
            sql += " ORDER BY opened_at, escalation_uid"
            return [self._escalation_dict(row) for row in connection.execute(sql, parameters)]
        finally:
            connection.close()

    def get_task_manifest(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            row = connection.execute(
                "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                raise BridgeError("manifest_not_found", f"task manifest does not exist: {task_id}")
            return self._manifest_dict(row)
        finally:
            connection.close()

    def set_task_manifest(
        self,
        task_id: str,
        agent_id: str,
        objective: str | None = None,
        acceptance_criteria: Sequence[str] | None = None,
        worklog_path: str | None = None,
        phase: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        objective = _validate_optional_text(objective, "objective", 4000)
        worklog_path = _validate_optional_text(worklog_path, "worklog_path", 2048)
        criteria = None if acceptance_criteria is None else _validate_criteria(acceptance_criteria)
        if phase is not None and phase not in ("active", "blocked"):
            raise BridgeError("invalid_phase", "manifest updates may use active or blocked")
        updated_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            self._require_task(connection, task_id)
            self._require_owner(connection, task_id, agent_id)
            current = connection.execute(
                "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()
            if current["phase"] == "archived":
                raise BridgeError("task_archived", f"task is archived: {task_id}")
            next_objective = objective if objective is not None else current["objective"]
            next_criteria = (
                criteria
                if criteria is not None
                else json.loads(current["acceptance_criteria_json"])
            )
            next_worklog = worklog_path if worklog_path is not None else current["worklog_path"]
            next_phase = phase if phase is not None else current["phase"]
            connection.execute(
                """
                UPDATE task_manifest
                SET objective = ?, acceptance_criteria_json = ?, worklog_path = ?,
                    phase = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    next_objective,
                    json.dumps(next_criteria, ensure_ascii=False, separators=(",", ":")),
                    next_worklog,
                    next_phase,
                    updated_at,
                    task_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._manifest_dict(row)

    def close_task(
        self,
        task_id: str,
        agent_id: str,
        phase: str = "completed",
        reason: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if phase not in ("completed", "cancelled"):
            raise BridgeError("invalid_phase", "task close phase must be completed or cancelled")
        reason = _validate_optional_text(reason, "reason", 2000)
        closed_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            self._require_owner(connection, task_id, agent_id)
            if task["status"] != "open":
                raise BridgeError("task_not_open", f"task is already closed: {task_id}")
            connection.execute("UPDATE tasks SET status = 'closed' WHERE task_id = ?", (task_id,))
            connection.execute(
                """
                UPDATE task_manifest
                SET phase = ?, updated_at = ?, closed_at = ?, closed_by = ?, closed_reason = ?
                WHERE task_id = ?
                """,
                (phase, closed_at, closed_at, agent_id, reason, task_id),
            )
            connection.execute(
                """
                UPDATE join_requests
                SET status = 'denied', resolved_by = ?, resolved_at = ?,
                    resolution_note = COALESCE(resolution_note, ?)
                WHERE task_id = ? AND status = 'pending'
                """,
                (agent_id, closed_at, f"task {phase}", task_id),
            )
            connection.execute(
                """
                UPDATE invitations
                SET revoked_at = ?, revoked_by = ?
                WHERE task_id = ? AND consumed_at IS NULL AND revoked_at IS NULL
                """,
                (closed_at, agent_id, task_id),
            )
            connection.execute(
                """
                UPDATE work_claims
                SET state = 'released', finalized_at = ?, result_code = 'task_closed'
                WHERE task_id = ? AND state = 'claimed'
                """,
                (closed_at, task_id),
            )
            connection.execute("DELETE FROM leader_leases WHERE task_id = ?", (task_id,))
            connection.execute(
                """
                UPDATE escalations
                SET state = 'resolved', resolved_at = ?, resolved_by = ?,
                    resolution_code = 'task_closed'
                WHERE task_id = ? AND state = 'open'
                """,
                (closed_at, agent_id, task_id),
            )
            row = connection.execute(
                "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()
        return {"task_id": task_id, "status": "closed", **self._manifest_dict(row)}

    def reopen_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        updated_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            manifest = self._require_owner(connection, task_id, agent_id)
            if manifest["phase"] == "archived":
                raise BridgeError("task_archived", f"task is archived: {task_id}")
            if task["status"] != "closed":
                raise BridgeError("task_not_closed", f"task is not closed: {task_id}")
            connection.execute("UPDATE tasks SET status = 'open' WHERE task_id = ?", (task_id,))
            connection.execute(
                "UPDATE task_manifest SET phase = 'active', updated_at = ?, closed_at = NULL, closed_by = NULL, closed_reason = NULL WHERE task_id = ?",
                (updated_at, task_id),
            )
        return self.get_task_manifest(task_id, agent_id)

    def archive_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        archived_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            manifest = self._require_owner(connection, task_id, agent_id)
            if task["status"] != "closed":
                raise BridgeError(
                    "task_not_closed", f"task must be closed before archive: {task_id}"
                )
            if manifest["phase"] == "archived":
                return self._manifest_dict(manifest)
            connection.execute(
                "UPDATE task_manifest SET phase = 'archived', updated_at = ?, archived_at = ?, archived_by = ? WHERE task_id = ?",
                (archived_at, archived_at, agent_id, task_id),
            )
            row = connection.execute(
                "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._manifest_dict(row)

    def join_task(self, task_id: str, agent_id: str, requested_by: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        requested_by = _validate_agent_id(requested_by)
        joined_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            if task["status"] != "open":
                raise BridgeError("task_closed", f"task is closed: {task_id}")
            self._require_member(connection, task_id, requested_by)
            connection.execute(
                """
                INSERT OR IGNORE INTO participants(
                    task_id, agent_id, joined_at, admission_method,
                    authorized_by, admission_ref
                ) VALUES(?, ?, ?, 'direct', ?, NULL)
                """,
                (task_id, agent_id, joined_at, requested_by),
            )
            participant = self._require_member(connection, task_id, agent_id)
        return {
            "task_id": task_id,
            "agent_id": agent_id,
            "requested_by": requested_by,
            "joined_at": participant["joined_at"],
            "admission_method": participant["admission_method"],
        }

    def set_task_access(
        self,
        task_id: str,
        agent_id: str,
        join_policy: str,
        discovery_summary: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if join_policy not in JOIN_POLICIES:
            raise BridgeError(
                "invalid_join_policy",
                f"join_policy must be one of: {', '.join(JOIN_POLICIES)}",
            )
        discovery_summary = _validate_optional_text(discovery_summary, "discovery_summary", 1000)
        updated_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            connection.execute(
                """
                INSERT INTO task_access(
                    task_id, join_policy, discovery_summary, updated_by, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    join_policy = excluded.join_policy,
                    discovery_summary = excluded.discovery_summary,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (task_id, join_policy, discovery_summary, agent_id, updated_at),
            )
        return {
            "task_id": task_id,
            "join_policy": join_policy,
            "discovery_summary": discovery_summary,
            "updated_by": agent_id,
            "updated_at": updated_at,
        }

    def discover_tasks(
        self, agent_id: str, query: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        agent_id = _validate_agent_id(agent_id)
        query = _validate_optional_text(query, "query", 1000)
        if limit < 1 or limit > 200:
            raise BridgeError("invalid_limit", "limit must be between 1 and 200")
        connection = self._connect()
        try:
            self._require_schema(connection)
            parameters: list[Any] = [agent_id]
            query_clause = ""
            if query:
                terms = [term for term in query.split() if term][:16]
                if not terms:
                    terms = [query]
                clauses = []
                for term in terms:
                    clauses.append(
                        "(t.task_id LIKE ? OR t.title LIKE ? OR a.discovery_summary LIKE ?)"
                    )
                    pattern = f"%{term}%"
                    parameters.extend((pattern, pattern, pattern))
                query_clause = "AND " + " AND ".join(clauses)
            parameters.append(limit)
            rows = connection.execute(
                f"""
                SELECT t.task_id, t.title, t.status, a.discovery_summary,
                       a.join_policy, a.updated_at
                FROM tasks t
                JOIN task_access a ON a.task_id = t.task_id
                WHERE t.status = 'open'
                  AND a.join_policy = 'request'
                  AND NOT EXISTS (
                      SELECT 1 FROM participants p
                      WHERE p.task_id = t.task_id AND p.agent_id = ?
                  )
                  {query_clause}
                ORDER BY a.updated_at DESC, t.task_id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def create_join_request(self, task_id: str, agent_id: str, message: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        message = _validate_text(message, "message", 2000)
        created_at = utc_now()
        request_uid = str(uuid4())
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            if task["status"] != "open":
                raise BridgeError("task_closed", f"task is closed: {task_id}")
            if connection.execute(
                "SELECT 1 FROM participants WHERE task_id = ? AND agent_id = ?",
                (task_id, agent_id),
            ).fetchone():
                raise BridgeError(
                    "already_participant",
                    f"agent {agent_id} is already a participant of {task_id}",
                )
            access = connection.execute(
                "SELECT join_policy FROM task_access WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not access or access["join_policy"] != "request":
                raise BridgeError(
                    "join_requests_disabled",
                    f"task does not accept join requests: {task_id}",
                )
            existing = connection.execute(
                """
                SELECT * FROM join_requests
                WHERE task_id = ? AND agent_id = ? AND status = 'pending'
                """,
                (task_id, agent_id),
            ).fetchone()
            if existing:
                result = self._request_dict(existing)
                result["created"] = False
                return result
            try:
                connection.execute(
                    """
                    INSERT INTO join_requests(
                        request_uid, task_id, agent_id, message, status, created_at
                    ) VALUES(?, ?, ?, ?, 'pending', ?)
                    """,
                    (request_uid, task_id, agent_id, message, created_at),
                )
            except sqlite3.IntegrityError:
                # The partial unique index is the final concurrency guard. A
                # simultaneous identical request is treated as an idempotent read.
                existing = connection.execute(
                    """
                    SELECT * FROM join_requests
                    WHERE task_id = ? AND agent_id = ? AND status = 'pending'
                    """,
                    (task_id, agent_id),
                ).fetchone()
                if not existing:
                    raise
                result = self._request_dict(existing)
                result["created"] = False
                return result
            row = connection.execute(
                "SELECT * FROM join_requests WHERE request_uid = ?", (request_uid,)
            ).fetchone()
        result = self._request_dict(row)
        result["created"] = True
        return result

    def list_join_requests(
        self, task_id: str, agent_id: str, status: str = "pending"
    ) -> list[dict[str, Any]]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if status not in (*JOIN_REQUEST_STATUSES, "all"):
            raise BridgeError(
                "invalid_request_status",
                f"status must be one of: {', '.join((*JOIN_REQUEST_STATUSES, 'all'))}",
            )
        connection = self._connect()
        try:
            self._require_schema(connection)
            self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            clause = "" if status == "all" else "AND status = ?"
            parameters: list[Any] = [task_id]
            if status != "all":
                parameters.append(status)
            rows = connection.execute(
                f"""
                SELECT * FROM join_requests
                WHERE task_id = ? {clause}
                ORDER BY created_at, request_uid
                """,
                parameters,
            ).fetchall()
            return [self._request_dict(row) for row in rows]
        finally:
            connection.close()

    def get_join_request(self, request_uid: str, agent_id: str) -> dict[str, Any]:
        request_uid = _validate_text(request_uid, "request_uid", 128)
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM join_requests WHERE request_uid = ?", (request_uid,)
            ).fetchone()
            if not row:
                raise BridgeError(
                    "join_request_not_found",
                    f"join request does not exist: {request_uid}",
                )
            if row["agent_id"] != agent_id:
                self._require_member(connection, row["task_id"], agent_id)
            return self._request_dict(row)
        finally:
            connection.close()

    def resolve_join_request(
        self,
        request_uid: str,
        agent_id: str,
        decision: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        request_uid = _validate_text(request_uid, "request_uid", 128)
        agent_id = _validate_agent_id(agent_id)
        if decision not in ("approve", "deny"):
            raise BridgeError("invalid_decision", "decision must be approve or deny")
        note = _validate_optional_text(note, "note", 2000)
        resolved_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM join_requests WHERE request_uid = ?", (request_uid,)
            ).fetchone()
            if not row:
                raise BridgeError(
                    "join_request_not_found",
                    f"join request does not exist: {request_uid}",
                )
            self._require_member(connection, row["task_id"], agent_id)
            if row["status"] != "pending":
                raise BridgeError(
                    "join_request_resolved",
                    f"join request is already {row['status']}: {request_uid}",
                )
            status = "approved" if decision == "approve" else "denied"
            joined = False
            if status == "approved":
                task = self._require_task(connection, row["task_id"])
                if task["status"] != "open":
                    raise BridgeError("task_closed", f"task is closed: {row['task_id']}")
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO participants(
                        task_id, agent_id, joined_at, admission_method,
                        authorized_by, admission_ref
                    ) VALUES(?, ?, ?, 'request', ?, ?)
                    """,
                    (
                        row["task_id"],
                        row["agent_id"],
                        resolved_at,
                        agent_id,
                        request_uid,
                    ),
                )
                joined = cursor.rowcount == 1
            connection.execute(
                """
                UPDATE join_requests
                SET status = ?, resolved_by = ?, resolved_at = ?, resolution_note = ?
                WHERE request_uid = ? AND status = 'pending'
                """,
                (status, agent_id, resolved_at, note, request_uid),
            )
            resolved = connection.execute(
                "SELECT * FROM join_requests WHERE request_uid = ?", (request_uid,)
            ).fetchone()
        result = self._request_dict(resolved)
        result["joined"] = joined
        return result

    def create_invitation(
        self,
        task_id: str,
        target_agent_id: str,
        created_by: str,
        expires_in_minutes: int = 60,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        target_agent_id = _validate_agent_id(target_agent_id)
        created_by = _validate_agent_id(created_by)
        if expires_in_minutes < 1 or expires_in_minutes > 10080:
            raise BridgeError("invalid_expiry", "expires_in_minutes must be between 1 and 10080")
        token = "abi_" + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        invitation_uid = str(uuid4())
        created_at = utc_now()
        expires_at = (
            (datetime.now(UTC) + timedelta(minutes=expires_in_minutes))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            if task["status"] != "open":
                raise BridgeError("task_closed", f"task is closed: {task_id}")
            self._require_member(connection, task_id, created_by)
            if connection.execute(
                "SELECT 1 FROM participants WHERE task_id = ? AND agent_id = ?",
                (task_id, target_agent_id),
            ).fetchone():
                raise BridgeError(
                    "already_participant",
                    f"agent {target_agent_id} is already a participant of {task_id}",
                )
            connection.execute(
                """
                INSERT INTO invitations(
                    invitation_uid, token_hash, task_id, target_agent_id,
                    created_by, created_at, expires_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invitation_uid,
                    token_hash,
                    task_id,
                    target_agent_id,
                    created_by,
                    created_at,
                    expires_at,
                ),
            )
        return {
            "invitation_uid": invitation_uid,
            "task_id": task_id,
            "target_agent_id": target_agent_id,
            "created_by": created_by,
            "created_at": created_at,
            "expires_at": expires_at,
            "token": token,
        }

    def list_invitations(self, task_id: str, agent_id: str) -> list[dict[str, Any]]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            rows = connection.execute(
                """
                SELECT invitation_uid, task_id, target_agent_id, created_by,
                       created_at, expires_at, consumed_at, consumed_by,
                       revoked_at, revoked_by
                FROM invitations WHERE task_id = ? ORDER BY created_at DESC
                """,
                (task_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def revoke_invitation(self, invitation_uid: str, agent_id: str) -> dict[str, Any]:
        invitation_uid = _validate_text(invitation_uid, "invitation_uid", 128)
        agent_id = _validate_agent_id(agent_id)
        revoked_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM invitations WHERE invitation_uid = ?",
                (invitation_uid,),
            ).fetchone()
            if not row:
                raise BridgeError(
                    "invitation_not_found",
                    f"invitation does not exist: {invitation_uid}",
                )
            self._require_member(connection, row["task_id"], agent_id)
            if row["consumed_at"]:
                raise BridgeError("invitation_consumed", "invitation is already consumed")
            if row["revoked_at"]:
                return self._invitation_dict(row)
            connection.execute(
                "UPDATE invitations SET revoked_at = ?, revoked_by = ? WHERE invitation_uid = ?",
                (revoked_at, agent_id, invitation_uid),
            )
            row = connection.execute(
                "SELECT * FROM invitations WHERE invitation_uid = ?",
                (invitation_uid,),
            ).fetchone()
        return self._invitation_dict(row)

    def redeem_invitation(self, token: str, agent_id: str) -> dict[str, Any]:
        token = _validate_text(token, "token", 512)
        agent_id = _validate_agent_id(agent_id)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        joined_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM invitations WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if not row:
                raise BridgeError("invalid_invitation", "invitation token is invalid")
            if row["target_agent_id"] != agent_id:
                raise BridgeError(
                    "invitation_target_mismatch", "invitation is bound to another Agent"
                )
            if row["consumed_at"]:
                raise BridgeError("invitation_consumed", "invitation is already consumed")
            if row["revoked_at"]:
                raise BridgeError("invitation_revoked", "invitation is revoked")
            if _parse_utc(row["expires_at"]) <= datetime.now(UTC):
                raise BridgeError("invitation_expired", "invitation has expired")
            task = self._require_task(connection, row["task_id"])
            if task["status"] != "open":
                raise BridgeError("task_closed", f"task is closed: {row['task_id']}")
            connection.execute(
                """
                INSERT OR IGNORE INTO participants(
                    task_id, agent_id, joined_at, admission_method,
                    authorized_by, admission_ref
                ) VALUES(?, ?, ?, 'invite', ?, ?)
                """,
                (
                    row["task_id"],
                    agent_id,
                    joined_at,
                    row["created_by"],
                    row["invitation_uid"],
                ),
            )
            connection.execute(
                """
                UPDATE invitations SET consumed_at = ?, consumed_by = ?
                WHERE invitation_uid = ? AND consumed_at IS NULL
                """,
                (joined_at, agent_id, row["invitation_uid"]),
            )
            participant = connection.execute(
                "SELECT * FROM participants WHERE task_id = ? AND agent_id = ?",
                (row["task_id"], agent_id),
            ).fetchone()
        return {
            "invitation_uid": row["invitation_uid"],
            "task_id": row["task_id"],
            "agent_id": agent_id,
            "joined_at": participant["joined_at"],
            "admission_method": participant["admission_method"],
            "authorized_by": participant["authorized_by"],
        }

    def list_tasks(self, agent_id: str) -> list[dict[str, Any]]:
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            rows = connection.execute(
                """
                SELECT t.*, p.last_read_event_id,
                    m.objective, m.acceptance_criteria_json, m.worklog_path,
                    m.owner_agent, m.phase, m.updated_at AS manifest_updated_at,
                    l.leader_agent, l.epoch AS leader_epoch,
                    (SELECT COUNT(*) FROM events e
                     WHERE e.task_id = t.task_id AND e.event_id > p.last_read_event_id
                       AND e.source_agent <> ?
                       AND (e.target_agent IS NULL OR e.target_agent = ?)) AS unread
                FROM tasks t
                JOIN participants p ON p.task_id = t.task_id
                LEFT JOIN task_manifest m ON m.task_id = t.task_id
                LEFT JOIN task_leadership l ON l.task_id = t.task_id
                WHERE p.agent_id = ?
                ORDER BY t.created_at DESC
                """,
                (agent_id, agent_id, agent_id),
            ).fetchall()
            results = []
            for row in rows:
                value = dict(row)
                raw = value.pop("acceptance_criteria_json", "[]")
                value["acceptance_criteria"] = json.loads(raw)
                results.append(value)
            return results
        finally:
            connection.close()

    def publish(
        self,
        task_id: str,
        source_agent: str,
        kind: str,
        summary: str,
        details: str | None = None,
        evidence: Sequence[str] = (),
        reply_to_uid: str | None = None,
        target_agent: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        source_agent = _validate_agent_id(source_agent)
        if target_agent is not None:
            target_agent = _validate_agent_id(target_agent)
        if kind not in EVENT_KINDS:
            raise BridgeError("invalid_kind", f"kind must be one of: {', '.join(EVENT_KINDS)}")
        summary = _validate_text(summary, "summary", 4000)
        if details is not None:
            details = _validate_text(details, "details", 16000)
        evidence_items = []
        for item in evidence:
            evidence_items.append(_validate_text(item, "evidence", 2048))
        if len(evidence_items) > 32:
            raise BridgeError("invalid_evidence", "at most 32 evidence references are allowed")
        event_uid = str(uuid4())
        created_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            if task["status"] != "open":
                raise BridgeError("task_closed", f"task is closed: {task_id}")
            self._require_member(connection, task_id, source_agent)
            if target_agent is not None:
                self._require_member(connection, task_id, target_agent)
            leadership = connection.execute(
                "SELECT leader_agent, epoch FROM task_leadership WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            leader_epoch = (
                leadership["epoch"]
                if leadership and leadership["leader_agent"] == source_agent
                else None
            )
            if reply_to_uid:
                parent = connection.execute(
                    "SELECT task_id FROM events WHERE event_uid = ?", (reply_to_uid,)
                ).fetchone()
                if not parent or parent["task_id"] != task_id:
                    raise BridgeError(
                        "invalid_reply",
                        "reply target is missing or belongs to another task",
                    )
            cursor = connection.execute(
                """
                INSERT INTO events(
                    event_uid, task_id, source_agent, kind, summary, details,
                    reply_to_uid, evidence_json, target_agent, leader_epoch, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_uid,
                    task_id,
                    source_agent,
                    kind,
                    summary,
                    details,
                    reply_to_uid,
                    json.dumps(evidence_items, ensure_ascii=False, separators=(",", ":")),
                    target_agent,
                    leader_epoch,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM events WHERE event_id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._event_dict(row)

    @staticmethod
    def _wake_claim_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _expire_live_wake_claim(
        connection: sqlite3.Connection, event_uid: str, now: str
    ) -> sqlite3.Row | None:
        row = connection.execute(
            "SELECT * FROM wake_claims WHERE event_uid = ? AND state = 'claimed'",
            (event_uid,),
        ).fetchone()
        if row and _parse_utc(row["lease_expires_at"]) <= _parse_utc(now):
            connection.execute(
                """
                UPDATE wake_claims
                SET state = 'expired_unknown', finalized_at = ?, result_code = 'lease_expired'
                WHERE claim_uid = ?
                """,
                (now, row["claim_uid"]),
            )
            refreshed = connection.execute(
                "SELECT * FROM wake_claims WHERE claim_uid = ?", (row["claim_uid"],)
            ).fetchone()
            return cast(sqlite3.Row | None, refreshed)
        return cast(sqlite3.Row | None, row)

    def claim_wake(
        self,
        task_id: str,
        event_uid: str,
        claimer_agent: str,
        adapter_id: str,
        attempt_uid: str,
        lease_seconds: int = 120,
        retry_claim_uid: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        claimer_agent = _validate_agent_id(claimer_agent)
        adapter_id = _validate_adapter_id(adapter_id)
        attempt_uid = _validate_uuid(attempt_uid, "attempt_id")
        if retry_claim_uid is not None:
            retry_claim_uid = _validate_uuid(retry_claim_uid, "retry_claim_id")
        if lease_seconds < 1 or lease_seconds > 600:
            raise BridgeError("invalid_lease_seconds", "lease_seconds must be between 1 and 600")

        now = utc_now()
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=lease_seconds))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            if task["status"] != "open":
                raise BridgeError("task_closed", f"task is closed: {task_id}")
            self._require_member(connection, task_id, claimer_agent)
            event = connection.execute(
                "SELECT * FROM events WHERE event_uid = ?", (event_uid,)
            ).fetchone()
            if not event or event["task_id"] != task_id:
                raise BridgeError("event_not_found", "event does not exist in this task")
            if event["target_agent"] != claimer_agent:
                raise BridgeError("wake_target_mismatch", "wake claimer is not the event target")
            if event["kind"] not in WAKE_CLAIMABLE_KINDS:
                raise BridgeError(
                    "wake_kind_not_claimable",
                    "only targeted request or handoff events may be claimed",
                )
            leadership = self._require_leadership(connection, task_id)
            if (
                event["source_agent"] != leadership["leader_agent"]
                or event["leader_epoch"] is None
                or event["leader_epoch"] != leadership["epoch"]
            ):
                raise BridgeError(
                    "wake_leadership_stale",
                    "event is not from the current task leader and epoch",
                )

            live_or_expired = self._expire_live_wake_claim(connection, event_uid, now)
            if live_or_expired and live_or_expired["state"] == "claimed":
                if live_or_expired["attempt_uid"] == attempt_uid:
                    return self._wake_claim_dict(live_or_expired)
                raise BridgeError("wake_already_claimed", "event already has a live wake claim")
            existing_attempt = connection.execute(
                "SELECT * FROM wake_claims WHERE attempt_uid = ?", (attempt_uid,)
            ).fetchone()
            if existing_attempt:
                if (
                    existing_attempt["event_uid"] != event_uid
                    or existing_attempt["claimer_agent"] != claimer_agent
                    or existing_attempt["adapter_id"] != adapter_id
                ):
                    raise BridgeError(
                        "wake_attempt_conflict",
                        "attempt_id is already bound to another wake claim",
                    )
                if existing_attempt["state"] == "expired_unknown":
                    raise BridgeError(
                        "wake_claim_expired_unknown",
                        "expired wake claim requires a new leader event; it cannot be retried",
                    )
                return self._wake_claim_dict(existing_attempt)
            previous = connection.execute(
                "SELECT * FROM wake_claims WHERE event_uid = ? ORDER BY claimed_at DESC LIMIT 1",
                (event_uid,),
            ).fetchone()
            if previous:
                if previous["state"] == "dispatched":
                    raise BridgeError("wake_dispatched", "event was already dispatched")
                if previous["state"] == "expired_unknown":
                    raise BridgeError(
                        "wake_claim_expired_unknown",
                        "expired wake claim requires a new leader event; it cannot be retried",
                    )
                if previous["state"] != "launch_failed" or retry_claim_uid != previous["claim_uid"]:
                    raise BridgeError(
                        "wake_retry_required",
                        "a launch_failed claim requires its explicit retry_claim_id",
                    )

            claim_uid = str(uuid4())
            connection.execute(
                """
                INSERT INTO wake_claims(
                    claim_uid, attempt_uid, task_id, event_uid, target_agent, claimer_agent,
                    adapter_id, leader_agent, leader_epoch, state, claimed_at,
                    lease_expires_at, supersedes_claim_uid
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed', ?, ?, ?)
                """,
                (
                    claim_uid,
                    attempt_uid,
                    task_id,
                    event_uid,
                    event["target_agent"],
                    claimer_agent,
                    adapter_id,
                    leadership["leader_agent"],
                    leadership["epoch"],
                    now,
                    expires_at,
                    previous["claim_uid"] if previous else None,
                ),
            )
            row = connection.execute(
                "SELECT * FROM wake_claims WHERE claim_uid = ?", (claim_uid,)
            ).fetchone()
        return self._wake_claim_dict(row)

    def finish_wake_claim(
        self,
        claim_uid: str,
        claimer_agent: str,
        outcome: str,
        result_code: str | None = None,
    ) -> dict[str, Any]:
        claim_uid = _validate_uuid(claim_uid, "claim_id")
        claimer_agent = _validate_agent_id(claimer_agent)
        if outcome not in ("dispatched", "launch_failed"):
            raise BridgeError("invalid_wake_outcome", "outcome must be dispatched or launch_failed")
        result_code = _validate_result_code(result_code)
        now = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM wake_claims WHERE claim_uid = ?", (claim_uid,)
            ).fetchone()
            if not row:
                raise BridgeError("wake_claim_not_found", "wake claim does not exist")
            self._require_member(connection, row["task_id"], claimer_agent)
            if row["claimer_agent"] != claimer_agent:
                raise BridgeError("wake_claimer_mismatch", "wake claim belongs to another claimer")
            current = self._expire_live_wake_claim(connection, row["event_uid"], now)
            if (
                current
                and current["claim_uid"] == claim_uid
                and current["state"] == "expired_unknown"
            ):
                raise BridgeError("wake_claim_expired_unknown", "wake claim expired before finish")
            row = connection.execute(
                "SELECT * FROM wake_claims WHERE claim_uid = ?", (claim_uid,)
            ).fetchone()
            if row["state"] != "claimed":
                raise BridgeError("wake_claim_not_live", f"wake claim is already {row['state']}")
            connection.execute(
                """
                UPDATE wake_claims SET state = ?, finalized_at = ?, result_code = ?
                WHERE claim_uid = ?
                """,
                (outcome, now, result_code, claim_uid),
            )
            row = connection.execute(
                "SELECT * FROM wake_claims WHERE claim_uid = ?", (claim_uid,)
            ).fetchone()
        return self._wake_claim_dict(row)

    def get_wake_claim(self, claim_uid: str, agent_id: str) -> dict[str, Any]:
        claim_uid = _validate_uuid(claim_uid, "claim_id")
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM wake_claims WHERE claim_uid = ?", (claim_uid,)
            ).fetchone()
            if not row:
                raise BridgeError("wake_claim_not_found", "wake claim does not exist")
            self._require_member(connection, row["task_id"], agent_id)
            if agent_id not in (row["target_agent"], row["leader_agent"]):
                raise BridgeError(
                    "wake_claim_not_visible", "wake claim is not visible to this agent"
                )
            return self._wake_claim_dict(row)
        finally:
            connection.close()

    @staticmethod
    def _work_package_dict(rows: Sequence[sqlite3.Row], now: str | None = None) -> dict[str, Any]:
        first = rows[0]
        states = {row["state"] for row in rows}
        state = next(iter(states)) if len(states) == 1 else "mixed"
        effective_state = state
        if (
            state == "claimed"
            and now is not None
            and _parse_utc(first["lease_expires_at"]) <= _parse_utc(now)
        ):
            effective_state = "expired_unknown"
        return {
            "package_uid": first["package_uid"],
            "task_id": first["task_id"],
            "worker_agent": first["worker_agent"],
            "leader_agent": first["leader_agent"],
            "leader_epoch": first["leader_epoch"],
            "state": state,
            "effective_state": effective_state,
            "resources": sorted(row["resource_id"] for row in rows),
            "claimed_at": first["claimed_at"],
            "lease_expires_at": first["lease_expires_at"],
            "finalized_at": first["finalized_at"],
            "result_code": first["result_code"],
            "supersedes_package_uid": first["supersedes_package_uid"],
        }

    def claim_work(
        self,
        task_id: str,
        leader_agent: str,
        worker_agent: str,
        resource_ids: Sequence[str],
        package_uid: str,
        lease_seconds: int = 900,
        takeover_package_uid: str | None = None,
    ) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        leader_agent = _validate_agent_id(leader_agent)
        worker_agent = _validate_agent_id(worker_agent)
        package_uid = _validate_uuid(package_uid, "package_id")
        if takeover_package_uid is not None:
            takeover_package_uid = _validate_uuid(takeover_package_uid, "takeover_package_id")
        if lease_seconds < 1 or lease_seconds > 86400:
            raise BridgeError("invalid_lease_seconds", "lease_seconds must be between 1 and 86400")
        resources = [_validate_resource_id(item) for item in resource_ids]
        if not resources or len(resources) > 32:
            raise BridgeError(
                "invalid_resources",
                "between 1 and 32 resource identifiers are required",
            )
        if len(set(resources)) != len(resources):
            raise BridgeError("duplicate_resource", "resource identifiers must be unique")
        resources.sort()

        now = utc_now()
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=lease_seconds))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        with self._transaction() as connection:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            if task["status"] != "open":
                raise BridgeError("task_closed", f"task is closed: {task_id}")
            self._require_member(connection, task_id, leader_agent)
            self._require_member(connection, task_id, worker_agent)
            leadership = self._require_leadership(connection, task_id)
            if leadership["leader_agent"] != leader_agent:
                raise BridgeError(
                    "not_task_leader",
                    "only the current task leader can allocate work resources",
                )

            existing = connection.execute(
                "SELECT * FROM work_claims WHERE package_uid = ? ORDER BY resource_id",
                (package_uid,),
            ).fetchall()
            if existing:
                same_contract = (
                    existing[0]["task_id"] == task_id
                    and existing[0]["worker_agent"] == worker_agent
                    and existing[0]["leader_agent"] == leader_agent
                    and existing[0]["leader_epoch"] == leadership["epoch"]
                    and [row["resource_id"] for row in existing] == resources
                )
                if not same_contract:
                    raise BridgeError(
                        "work_package_conflict",
                        "package_id is already bound to another work allocation",
                    )
                return self._work_package_dict(existing, now)

            expired_packages: set[str] = set()
            for resource_id in resources:
                active = connection.execute(
                    """
                    SELECT * FROM work_claims
                    WHERE task_id = ? AND resource_id = ? AND state = 'claimed'
                    """,
                    (task_id, resource_id),
                ).fetchone()
                if active:
                    if _parse_utc(active["lease_expires_at"]) > _parse_utc(now):
                        raise BridgeError(
                            "work_resource_claimed",
                            f"resource is already claimed: {resource_id}",
                        )
                    connection.execute(
                        """
                        UPDATE work_claims
                        SET state = 'expired_unknown', finalized_at = ?, result_code = 'lease_expired'
                        WHERE package_uid = ? AND state = 'claimed'
                        """,
                        (now, active["package_uid"]),
                    )

                latest = connection.execute(
                    """
                    SELECT * FROM work_claims
                    WHERE task_id = ? AND resource_id = ?
                    ORDER BY claimed_at DESC, package_uid DESC LIMIT 1
                    """,
                    (task_id, resource_id),
                ).fetchone()
                if latest and latest["state"] == "expired_unknown":
                    expired_packages.add(latest["package_uid"])

            if len(expired_packages) > 1:
                raise BridgeError(
                    "work_takeover_ambiguous",
                    "resources belong to multiple expired packages and must be reconciled separately",
                )
            expired_package = next(iter(expired_packages), None)
            if expired_package and takeover_package_uid != expired_package:
                raise BridgeError(
                    "work_takeover_required",
                    "expired work requires its explicit takeover_package_id",
                )
            if takeover_package_uid is not None and expired_package is None:
                raise BridgeError(
                    "work_takeover_not_required",
                    "takeover_package_id does not match an expired resource allocation",
                )

            connection.executemany(
                """
                INSERT INTO work_claims(
                    package_uid, resource_id, task_id, worker_agent,
                    leader_agent, leader_epoch, state, claimed_at,
                    lease_expires_at, supersedes_package_uid
                ) VALUES(?, ?, ?, ?, ?, ?, 'claimed', ?, ?, ?)
                """,
                [
                    (
                        package_uid,
                        resource_id,
                        task_id,
                        worker_agent,
                        leader_agent,
                        leadership["epoch"],
                        now,
                        expires_at,
                        expired_package,
                    )
                    for resource_id in resources
                ],
            )
            rows = connection.execute(
                "SELECT * FROM work_claims WHERE package_uid = ? ORDER BY resource_id",
                (package_uid,),
            ).fetchall()
        return self._work_package_dict(rows, now)

    def finish_work_claim(
        self,
        package_uid: str,
        agent_id: str,
        outcome: str,
        result_code: str | None = None,
    ) -> dict[str, Any]:
        package_uid = _validate_uuid(package_uid, "package_id")
        agent_id = _validate_agent_id(agent_id)
        if outcome not in ("completed", "failed", "released"):
            raise BridgeError(
                "invalid_work_outcome",
                "outcome must be completed, failed, or released",
            )
        result_code = _validate_result_code(result_code)
        now = utc_now()
        expired = False
        with self._transaction() as connection:
            self._require_schema(connection)
            rows = connection.execute(
                "SELECT * FROM work_claims WHERE package_uid = ? ORDER BY resource_id",
                (package_uid,),
            ).fetchall()
            if not rows:
                raise BridgeError("work_claim_not_found", "work package does not exist")
            self._require_member(connection, rows[0]["task_id"], agent_id)
            leadership = self._require_leadership(connection, rows[0]["task_id"])
            if agent_id not in (rows[0]["worker_agent"], leadership["leader_agent"]):
                raise BridgeError(
                    "work_claim_actor_mismatch",
                    "only the assigned worker or current leader can finish a work package",
                )
            states = {row["state"] for row in rows}
            if states == {outcome}:
                return self._work_package_dict(rows, now)
            if states != {"claimed"}:
                raise BridgeError(
                    "work_claim_not_live",
                    f"work package is already {','.join(sorted(states))}",
                )
            if _parse_utc(rows[0]["lease_expires_at"]) <= _parse_utc(now):
                connection.execute(
                    """
                    UPDATE work_claims
                    SET state = 'expired_unknown', finalized_at = ?, result_code = 'lease_expired'
                    WHERE package_uid = ? AND state = 'claimed'
                    """,
                    (now, package_uid),
                )
                expired = True
            else:
                connection.execute(
                    """
                    UPDATE work_claims
                    SET state = ?, finalized_at = ?, result_code = ?
                    WHERE package_uid = ? AND state = 'claimed'
                    """,
                    (outcome, now, result_code, package_uid),
                )
            rows = connection.execute(
                "SELECT * FROM work_claims WHERE package_uid = ? ORDER BY resource_id",
                (package_uid,),
            ).fetchall()
        if expired:
            raise BridgeError(
                "work_claim_expired_unknown",
                "work package expired before finish and requires explicit Leader reconciliation",
            )
        return self._work_package_dict(rows, now)

    def get_work_claim(self, package_uid: str, agent_id: str) -> dict[str, Any]:
        package_uid = _validate_uuid(package_uid, "package_id")
        agent_id = _validate_agent_id(agent_id)
        now = utc_now()
        connection = self._connect()
        try:
            self._require_schema(connection)
            rows = connection.execute(
                "SELECT * FROM work_claims WHERE package_uid = ? ORDER BY resource_id",
                (package_uid,),
            ).fetchall()
            if not rows:
                raise BridgeError("work_claim_not_found", "work package does not exist")
            self._require_member(connection, rows[0]["task_id"], agent_id)
            return self._work_package_dict(rows, now)
        finally:
            connection.close()

    def list_work_claims(
        self, task_id: str, agent_id: str, state: str | None = None
    ) -> list[dict[str, Any]]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if state is not None and state not in WORK_CLAIM_STATES:
            raise BridgeError(
                "invalid_work_state",
                f"state must be one of: {', '.join(WORK_CLAIM_STATES)}",
            )
        now = utc_now()
        connection = self._connect()
        try:
            self._require_schema(connection)
            self._require_member(connection, task_id, agent_id)
            state_clause = "AND state = ?" if state is not None else ""
            parameters: list[Any] = [task_id]
            if state is not None:
                parameters.append(state)
            rows = connection.execute(
                f"""
                SELECT * FROM work_claims
                WHERE task_id = ? {state_clause}
                ORDER BY claimed_at, package_uid, resource_id
                """,
                parameters,
            ).fetchall()
            grouped: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                grouped.setdefault(row["package_uid"], []).append(row)
            return [self._work_package_dict(items, now) for items in grouped.values()]
        finally:
            connection.close()

    def list_events(
        self,
        task_id: str,
        agent_id: str,
        after_event_id: int | None = None,
        limit: int = 50,
        include_own: bool = False,
    ) -> list[dict[str, Any]]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if limit < 1 or limit > 200:
            raise BridgeError("invalid_limit", "limit must be between 1 and 200")
        connection = self._connect()
        try:
            self._require_schema(connection)
            participant = self._require_member(connection, task_id, agent_id)
            cursor = participant["last_read_event_id"] if after_event_id is None else after_event_id
            if cursor < 0:
                raise BridgeError("invalid_cursor", "after_event_id must not be negative")
            own_clause = "" if include_own else "AND source_agent <> ?"
            visibility_clause = "AND (target_agent IS NULL OR target_agent = ? OR source_agent = ?)"
            parameters: list[Any] = [task_id, cursor, agent_id, agent_id]
            if not include_own:
                parameters.append(agent_id)
            parameters.append(limit)
            rows = connection.execute(
                f"SELECT * FROM events WHERE task_id = ? AND event_id > ? {visibility_clause} {own_clause} ORDER BY event_id LIMIT ?",
                parameters,
            ).fetchall()
            return [self._event_dict(row) for row in rows]
        finally:
            connection.close()

    def read_event(self, event_uid: str, agent_id: str) -> dict[str, Any]:
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM events WHERE event_uid = ?", (event_uid,)
            ).fetchone()
            if not row:
                raise BridgeError("event_not_found", f"event does not exist: {event_uid}")
            self._require_member(connection, row["task_id"], agent_id)
            if row["target_agent"] is not None and agent_id not in (
                row["target_agent"],
                row["source_agent"],
            ):
                raise BridgeError("event_not_visible", "event is targeted to another participant")
            return self._event_dict(row)
        finally:
            connection.close()

    def acknowledge(self, event_uid: str, agent_id: str) -> dict[str, Any]:
        agent_id = _validate_agent_id(agent_id)
        acknowledged_at = utc_now()
        with self._transaction() as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT * FROM events WHERE event_uid = ?", (event_uid,)
            ).fetchone()
            if not row:
                raise BridgeError("event_not_found", f"event does not exist: {event_uid}")
            self._require_member(connection, row["task_id"], agent_id)
            if row["target_agent"] is not None and agent_id not in (
                row["target_agent"],
                row["source_agent"],
            ):
                raise BridgeError("event_not_visible", "event is targeted to another participant")
            connection.execute(
                "INSERT OR REPLACE INTO acknowledgements(event_id, agent_id, acknowledged_at) VALUES(?, ?, ?)",
                (row["event_id"], agent_id, acknowledged_at),
            )
            connection.execute(
                """
                UPDATE participants
                SET last_read_event_id = MAX(last_read_event_id, ?)
                WHERE task_id = ? AND agent_id = ?
                """,
                (row["event_id"], row["task_id"], agent_id),
            )
        return {
            "event_uid": event_uid,
            "event_id": row["event_id"],
            "task_id": row["task_id"],
            "agent_id": agent_id,
            "acknowledged_at": acknowledged_at,
        }

    def status(self, task_id: str, agent_id: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            participant = self._require_member(connection, task_id, agent_id)
            unread = connection.execute(
                """
                SELECT COUNT(*) AS count FROM events
                WHERE task_id = ? AND event_id > ? AND source_agent <> ?
                  AND (target_agent IS NULL OR target_agent = ?)
                """,
                (task_id, participant["last_read_event_id"], agent_id, agent_id),
            ).fetchone()["count"]
            latest = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) AS value FROM events WHERE task_id = ?",
                (task_id,),
            ).fetchone()["value"]
            members = connection.execute(
                """
                SELECT agent_id, joined_at, last_read_event_id,
                       admission_method, authorized_by, admission_ref
                FROM participants WHERE task_id = ? ORDER BY agent_id
                """,
                (task_id,),
            ).fetchall()
            access = connection.execute(
                "SELECT join_policy, discovery_summary, updated_by, updated_at FROM task_access WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            manifest = connection.execute(
                "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()
            leadership = connection.execute(
                "SELECT leader_agent, epoch, updated_at, updated_by FROM task_leadership WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return {
                "task": dict(task),
                "access": dict(access) if access else None,
                "manifest": self._manifest_dict(manifest) if manifest else None,
                "leadership": dict(leadership) if leadership else None,
                "agent_id": agent_id,
                "last_read_event_id": participant["last_read_event_id"],
                "latest_event_id": latest,
                "unread": unread,
                "participants": [dict(member) for member in members],
            }
        finally:
            connection.close()

    def leader_view(
        self,
        task_id: str,
        agent_id: str,
        after_event_id: int = 0,
        limit: int = 50,
        stale_after_seconds: int = 300,
    ) -> dict[str, Any]:
        """Derive current-leader request state without writing projection state."""
        task_id = _validate_task_id(task_id)
        agent_id = _validate_agent_id(agent_id)
        if after_event_id < 0:
            raise BridgeError("invalid_cursor", "after_event_id must not be negative")
        if limit < 1 or limit > 200:
            raise BridgeError("invalid_limit", "limit must be between 1 and 200")
        if stale_after_seconds < 1 or stale_after_seconds > 604800:
            raise BridgeError(
                "invalid_stale_after_seconds",
                "stale_after_seconds must be between 1 and 604800",
            )

        generated_at = utc_now()
        generated_at_value = _parse_utc(generated_at)
        connection = self._connect()
        try:
            self._require_schema(connection)
            task = self._require_task(connection, task_id)
            self._require_member(connection, task_id, agent_id)
            leadership = self._require_leadership(connection, task_id)
            if leadership["leader_agent"] != agent_id:
                raise BridgeError(
                    "not_task_leader",
                    "leader view is available only to the current task leader",
                )
            manifest = connection.execute(
                "SELECT * FROM task_manifest WHERE task_id = ?", (task_id,)
            ).fetchone()
            request_rows = connection.execute(
                """
                SELECT * FROM events
                WHERE task_id = ? AND kind = 'request' AND source_agent = ?
                  AND leader_epoch = ? AND event_id > ?
                ORDER BY event_id DESC LIMIT ?
                """,
                (
                    task_id,
                    agent_id,
                    leadership["epoch"],
                    after_event_id,
                    limit,
                ),
            ).fetchall()

            threads = []
            state_counts = {
                "waiting": 0,
                "processing": 0,
                "answered": 0,
                "failed": 0,
                "overdue": 0,
            }
            responses_to_review = 0
            needs_user_attention = 0
            duplicate_response_threads = 0

            for request_row in reversed(request_rows):
                response_rows = connection.execute(
                    """
                    SELECT * FROM events
                    WHERE task_id = ? AND kind = 'response' AND reply_to_uid = ?
                      AND (target_agent IS NULL OR target_agent = ? OR source_agent = ?)
                    ORDER BY event_id
                    """,
                    (task_id, request_row["event_uid"], agent_id, agent_id),
                ).fetchall()
                acknowledgement_rows = connection.execute(
                    """
                    SELECT agent_id, acknowledged_at FROM acknowledgements
                    WHERE event_id = ? AND agent_id <> ?
                    ORDER BY acknowledged_at, agent_id
                    """,
                    (request_row["event_id"], request_row["source_agent"]),
                ).fetchall()
                claim_rows = connection.execute(
                    """
                    SELECT * FROM wake_claims
                    WHERE event_uid = ? ORDER BY claimed_at, claim_uid
                    """,
                    (request_row["event_uid"],),
                ).fetchall()

                acknowledgements = [dict(row) for row in acknowledgement_rows]
                responses = [self._event_dict(row) for row in response_rows]
                latest_claim = claim_rows[-1] if claim_rows else None
                claim = None
                if latest_claim:
                    claim = {
                        key: latest_claim[key]
                        for key in (
                            "claim_uid",
                            "adapter_id",
                            "state",
                            "claimed_at",
                            "lease_expires_at",
                            "finalized_at",
                            "result_code",
                            "supersedes_claim_uid",
                        )
                    }

                if responses:
                    base_state = "answered"
                    state = "answered"
                    reason = "linked_response"
                    attention = "review"
                    state_changed_at = responses[-1]["created_at"]
                elif latest_claim and latest_claim["state"] == "claimed":
                    base_state = "processing"
                    if _parse_utc(latest_claim["lease_expires_at"]) <= generated_at_value:
                        state = "failed"
                        reason = "claim_lease_expired_unfinalized"
                        attention = "required"
                    else:
                        state = "processing"
                        reason = "wake_claim_active"
                        attention = "none"
                    state_changed_at = latest_claim["claimed_at"]
                elif latest_claim and latest_claim["state"] in (
                    "launch_failed",
                    "expired_unknown",
                    "relinquished",
                ):
                    base_state = "failed"
                    state = "failed"
                    reason = f"wake_{latest_claim['state']}"
                    attention = "required"
                    state_changed_at = latest_claim["finalized_at"] or latest_claim["claimed_at"]
                elif latest_claim and latest_claim["state"] == "dispatched":
                    # A dispatched adapter contract includes a linked response. Missing one
                    # is a protocol failure, not a successful state to infer silently.
                    base_state = "failed"
                    state = "failed"
                    reason = "dispatched_without_visible_response"
                    attention = "required"
                    state_changed_at = latest_claim["finalized_at"] or latest_claim["claimed_at"]
                elif acknowledgements:
                    base_state = "processing"
                    state = "processing"
                    reason = "acknowledged_awaiting_response"
                    attention = "none"
                    state_changed_at = acknowledgements[-1]["acknowledged_at"]
                else:
                    base_state = "waiting"
                    state = "waiting"
                    reason = "awaiting_dispatch"
                    attention = "none"
                    state_changed_at = request_row["created_at"]

                age_seconds = max(
                    0,
                    int(
                        (generated_at_value - _parse_utc(request_row["created_at"])).total_seconds()
                    ),
                )
                if state in ("waiting", "processing") and age_seconds >= stale_after_seconds:
                    state = "overdue"
                    reason = f"stale_{reason}"
                    attention = "required"

                state_counts[state] += 1
                if attention == "required":
                    needs_user_attention += 1
                elif attention == "review":
                    responses_to_review += 1
                if len(responses) > 1:
                    duplicate_response_threads += 1

                threads.append(
                    {
                        "request": self._event_dict(request_row),
                        "state": state,
                        "base_state": base_state,
                        "reason": reason,
                        "user_attention": attention,
                        "age_seconds": age_seconds,
                        "state_changed_at": state_changed_at,
                        "acknowledgements": acknowledgements,
                        "latest_wake_claim": claim,
                        "wake_claim_count": len(claim_rows),
                        "responses": responses,
                        "response_count": len(responses),
                        "duplicate_response_count": max(0, len(responses) - 1),
                    }
                )

            work_rows = connection.execute(
                """
                SELECT * FROM work_claims
                WHERE task_id = ? AND state = 'claimed'
                ORDER BY claimed_at, package_uid, resource_id
                """,
                (task_id,),
            ).fetchall()
            grouped_work: dict[str, list[sqlite3.Row]] = {}
            for row in work_rows:
                grouped_work.setdefault(row["package_uid"], []).append(row)
            work_packages = [
                self._work_package_dict(items, generated_at) for items in grouped_work.values()
            ]
            expired_work_packages = sum(
                item["effective_state"] == "expired_unknown" for item in work_packages
            )

            return {
                "generated_at": generated_at,
                "task": dict(task),
                "manifest": self._manifest_dict(manifest) if manifest else None,
                "leadership": dict(leadership),
                "after_event_id": after_event_id,
                "stale_after_seconds": stale_after_seconds,
                "summary": {
                    "requests": len(threads),
                    **state_counts,
                    "responses_to_review": responses_to_review,
                    "needs_user_attention": needs_user_attention,
                    "duplicate_response_threads": duplicate_response_threads,
                    "active_work_packages": len(work_packages) - expired_work_packages,
                    "expired_work_packages": expired_work_packages,
                },
                "relay_policy": {
                    "required_states": ["failed", "overdue"],
                    "review_states": ["answered"],
                    "silent_states": ["waiting", "processing"],
                    "content_impact": "The Leader decides whether an answered event changes user decisions or task state.",
                },
                "requests": threads,
                "work_packages": work_packages,
            }
        finally:
            connection.close()

    def dashboard(self, agent_id: str) -> dict[str, Any]:
        agent_id = _validate_agent_id(agent_id)
        generated_at = utc_now()
        tasks = self.list_tasks(agent_id)
        connection = self._connect()
        try:
            self._require_schema(connection)
            for task in tasks:
                task["pending_join_requests"] = connection.execute(
                    "SELECT COUNT(*) FROM join_requests WHERE task_id = ? AND status = 'pending'",
                    (task["task_id"],),
                ).fetchone()[0]
                task["open_invitations"] = connection.execute(
                    """
                    SELECT COUNT(*) FROM invitations
                    WHERE task_id = ? AND consumed_at IS NULL AND revoked_at IS NULL
                      AND expires_at > ?
                    """,
                    (task["task_id"], generated_at),
                ).fetchone()[0]
            my_requests = [
                self._request_dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM join_requests
                    WHERE agent_id = ? ORDER BY created_at DESC, request_uid
                    """,
                    (agent_id,),
                ).fetchall()
            ]
            discoverable = connection.execute(
                """
                SELECT COUNT(*) FROM tasks t
                JOIN task_access a ON a.task_id = t.task_id
                WHERE t.status = 'open' AND a.join_policy = 'request'
                  AND NOT EXISTS (
                      SELECT 1 FROM participants p
                      WHERE p.task_id = t.task_id AND p.agent_id = ?
                  )
                """,
                (agent_id,),
            ).fetchone()[0]
            targeted_invitations = connection.execute(
                """
                SELECT COUNT(*) FROM invitations
                WHERE target_agent_id = ? AND consumed_at IS NULL AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (agent_id, generated_at),
            ).fetchone()[0]
        finally:
            connection.close()
        return {
            "generated_at": generated_at,
            "agent_id": agent_id,
            "summary": {
                "visible_tasks": len(tasks),
                "unread_events": sum(task["unread"] for task in tasks),
                "pending_join_requests": sum(task["pending_join_requests"] for task in tasks),
                "discoverable_tasks": discoverable,
                "targeted_invitations": targeted_invitations,
            },
            "tasks": tasks,
            "my_join_requests": my_requests,
            "health": self.health(allow_legacy=False),
        }

    def broker_shutdown_status(self, agent_ids: Sequence[str]) -> dict[str, Any]:
        """Summarize only whether registered Agents still have active bridge work.

        The Broker needs a fail-closed read model after sessions close.  It must
        not infer completion from a cursor advance, because an acknowledged
        request can still be awaiting its linked response or hold a live claim.
        """
        registered_agents = tuple(sorted({_validate_agent_id(value) for value in agent_ids}))
        if not registered_agents:
            raise BridgeError("invalid_agents", "at least one registered agent is required")
        placeholders = ",".join("?" for _ in registered_agents)
        active_task_clause = "t.status = 'open' AND m.phase = 'active'"
        connection = self._connect()
        try:
            self._require_schema(connection)
            pending_target_events = connection.execute(
                f"""
                SELECT COUNT(*) FROM events e
                JOIN tasks t ON t.task_id = e.task_id
                JOIN task_manifest m ON m.task_id = e.task_id
                WHERE {active_task_clause}
                  AND e.kind IN ('request', 'handoff')
                  AND e.target_agent IN ({placeholders})
                  AND NOT EXISTS (
                      SELECT 1 FROM events response
                      WHERE response.task_id = e.task_id
                        AND response.kind = 'response'
                        AND response.reply_to_uid = e.event_uid
                  )
                """,
                registered_agents,
            ).fetchone()[0]
            active_wake_claims = connection.execute(
                f"""
                SELECT COUNT(*) FROM wake_claims c
                JOIN tasks t ON t.task_id = c.task_id
                JOIN task_manifest m ON m.task_id = c.task_id
                WHERE {active_task_clause} AND c.state = 'claimed'
                  AND c.target_agent IN ({placeholders})
                """,
                registered_agents,
            ).fetchone()[0]
            active_work_claims = connection.execute(
                f"""
                SELECT COUNT(DISTINCT c.package_uid) FROM work_claims c
                JOIN tasks t ON t.task_id = c.task_id
                JOIN task_manifest m ON m.task_id = c.task_id
                WHERE {active_task_clause} AND c.state = 'claimed'
                  AND c.worker_agent IN ({placeholders})
                """,
                registered_agents,
            ).fetchone()[0]
        finally:
            connection.close()
        return {
            "registered_agents": list(registered_agents),
            "pending_target_events": pending_target_events,
            "active_wake_claims": active_wake_claims,
            "active_work_claims": active_work_claims,
            "ready": not (pending_target_events or active_wake_claims or active_work_claims),
        }

    def health(self, allow_legacy: bool = True) -> dict[str, Any]:
        connection = self._connect()
        try:
            version = self._require_supported_schema(connection)
            if not allow_legacy and version != SCHEMA_VERSION:
                raise BridgeError(
                    "unsupported_schema",
                    f"schema version {version} requires init migration to {SCHEMA_VERSION}",
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_violations = [
                dict(row) for row in connection.execute("PRAGMA foreign_key_check")
            ]
            if integrity != "ok" or foreign_key_violations:
                raise BridgeError(
                    "integrity_failed",
                    f"integrity={integrity}; foreign_key_violations={len(foreign_key_violations)}",
                )
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            tables = ["tasks", "participants", "events", "acknowledgements"]
            if version >= 2:
                tables.extend(["task_access", "join_requests", "invitations"])
            if version >= 3:
                tables.append("task_manifest")
            if version >= 4:
                tables.append("task_leadership")
            if version >= 5:
                tables.append("wake_claims")
            if version >= 6:
                tables.append("work_claims")
            if version >= 7:
                tables.extend(["leader_leases", "escalations"])
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
            return {
                "database": str(self.database),
                "schema_version": version,
                "migration_required": version != SCHEMA_VERSION,
                "integrity": integrity,
                "journal_mode": journal_mode,
                "counts": counts,
            }
        finally:
            connection.close()

    def snapshot(self, output: Path | str) -> dict[str, Any]:
        output_path = Path(output).expanduser().resolve()
        if output_path == self.database:
            raise BridgeError(
                "invalid_snapshot", "snapshot output must differ from the live database"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f"{output_path.name}.pending-{uuid4().hex}")
        try:
            source = self._connect()
            target = sqlite3.connect(temporary)
            try:
                self._require_supported_schema(source)
                source.backup(target)
                target.commit()
            finally:
                target.close()
                source.close()
            os.replace(temporary, output_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest().upper()
        return {
            "snapshot": str(output_path),
            "sha256": digest,
            "bytes": output_path.stat().st_size,
        }

    def restore(self, snapshot: Path | str, rollback_output: Path | str) -> dict[str, Any]:
        snapshot_path = Path(snapshot).expanduser().resolve()
        rollback_path = Path(rollback_output).expanduser().resolve()
        if snapshot_path in (self.database, rollback_path):
            raise BridgeError(
                "invalid_restore",
                "snapshot, live database, and rollback output must be different files",
            )
        if rollback_path == self.database:
            raise BridgeError(
                "invalid_restore", "rollback output must differ from the live database"
            )
        if not snapshot_path.is_file():
            raise BridgeError("invalid_restore", f"snapshot does not exist: {snapshot_path}")

        # Validate before taking the rollback copy so an invalid candidate cannot
        # create artifacts or change the current database.
        try:
            snapshot_health = ConversationBridge(snapshot_path).health()
        except (BridgeError, sqlite3.Error) as exc:
            raise BridgeError("invalid_restore", f"snapshot validation failed: {exc}") from exc

        rollback = self.snapshot(rollback_path)
        try:
            source = sqlite3.connect(snapshot_path, isolation_level=None)
            target = self._connect()
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
                # A legacy snapshot is accepted for recovery, then migrated in place
                # before it becomes the active database again.
                self.initialize()
                restored_health = self.health(allow_legacy=False)
        except Exception as restore_error:
            try:
                source = sqlite3.connect(rollback_path, isolation_level=None)
                target = self._connect()
                try:
                    source.backup(target)
                finally:
                    target.close()
                    source.close()
                self.health()
            except Exception as rollback_error:
                raise BridgeError(
                    "restore_failed",
                    f"restore failed ({restore_error}); automatic rollback also failed "
                    f"({rollback_error}); preserved rollback: {rollback_path}",
                ) from restore_error
            raise BridgeError(
                "restore_failed",
                f"restore failed and the original database was restored: {restore_error}",
            ) from restore_error

        return {
            "database": str(self.database),
            "snapshot": str(snapshot_path),
            "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest().upper(),
            "snapshot_health": snapshot_health,
            "rollback": rollback,
            "health": restored_health,
        }
