# ruff: noqa: E501

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ["PYTHONPATH"] = os.pathsep.join(
    (str(PROJECT_ROOT / "src"), os.environ.get("PYTHONPATH", ""))
)

from cohestra.bridge.db import BridgeError, ConversationBridge  # noqa: E402


class ConversationBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "bridge.sqlite3"
        self.bridge = ConversationBridge(self.database)
        self.bridge.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create_shared_task(self) -> None:
        self.bridge.create_task("framework/bridge", "Bridge implementation", "agent-alpha")
        self.bridge.join_task("framework/bridge", "agent-beta", "agent-alpha")

    def _run_cli(
        self, *arguments: str, database: Path | None = None
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        command = [
            sys.executable,
            "-m",
            "cohestra.bridge",
            "--db",
            str(database or self.database),
            *arguments,
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        stream = completed.stdout if completed.returncode == 0 else completed.stderr
        return completed, json.loads(stream)

    def test_task_event_acknowledgement_workflow(self) -> None:
        self._create_shared_task()
        event = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "handoff",
            "Core schema is ready",
            evidence=["evidence/handoff.md"],
        )

        pending = self.bridge.list_events("framework/bridge", "agent-beta")
        self.assertEqual([event["event_uid"]], [item["event_uid"] for item in pending])
        self.assertEqual(1, self.bridge.status("framework/bridge", "agent-beta")["unread"])

        acknowledgement = self.bridge.acknowledge(event["event_uid"], "agent-beta")
        self.assertEqual(event["event_id"], acknowledgement["event_id"])
        self.assertEqual([], self.bridge.list_events("framework/bridge", "agent-beta"))
        self.assertEqual(0, self.bridge.status("framework/bridge", "agent-beta")["unread"])

    def test_non_participant_cannot_read_or_publish(self) -> None:
        self._create_shared_task()
        with self.assertRaisesRegex(BridgeError, "not a participant"):
            self.bridge.list_events("framework/bridge", "other-agent")
        with self.assertRaisesRegex(BridgeError, "not a participant"):
            self.bridge.publish("framework/bridge", "other-agent", "update", "Should fail")

    def test_reply_must_stay_within_task(self) -> None:
        self._create_shared_task()
        self.bridge.create_task("other/task", "Other", "agent-alpha")
        parent = self.bridge.publish("other/task", "agent-alpha", "update", "Other event")
        with self.assertRaisesRegex(BridgeError, "another task"):
            self.bridge.publish(
                "framework/bridge",
                "agent-alpha",
                "response",
                "Invalid cross-task response",
                reply_to_uid=parent["event_uid"],
            )

    def test_snapshot_is_consistent(self) -> None:
        self._create_shared_task()
        self.bridge.publish("framework/bridge", "agent-alpha", "update", "Snapshot me")
        snapshot = self.root / "snapshot.sqlite3"
        result = self.bridge.snapshot(snapshot)
        self.assertTrue(snapshot.is_file())
        self.assertEqual("ok", ConversationBridge(snapshot).health()["integrity"])
        self.assertEqual(1, ConversationBridge(snapshot).health()["counts"]["events"])
        self.assertEqual(64, len(result["sha256"]))

    def test_failed_snapshot_leaves_no_temporary_file(self) -> None:
        uninitialized = self.root / "uninitialized.sqlite3"
        uninitialized.touch()
        output = self.root / "invalid-snapshot.sqlite3"
        with self.assertRaisesRegex(BridgeError, "schema"):
            ConversationBridge(uninitialized).snapshot(output)
        self.assertFalse(output.exists())
        self.assertEqual([], list(self.root.glob("invalid-snapshot.sqlite3.pending-*")))

    def test_restore_preserves_rollback_and_replaces_state(self) -> None:
        self._create_shared_task()
        self.bridge.publish("framework/bridge", "agent-alpha", "update", "Before snapshot")
        snapshot = self.root / "snapshot.sqlite3"
        self.bridge.snapshot(snapshot)
        self.bridge.publish("framework/bridge", "agent-alpha", "update", "After snapshot")

        rollback = self.root / "rollback.sqlite3"
        result = self.bridge.restore(snapshot, rollback)

        self.assertEqual(1, self.bridge.health()["counts"]["events"])
        self.assertEqual(2, ConversationBridge(rollback).health()["counts"]["events"])
        self.assertEqual("ok", result["health"]["integrity"])
        self.assertEqual(64, len(result["snapshot_sha256"]))

    def test_invalid_restore_does_not_change_live_database(self) -> None:
        self._create_shared_task()
        self.bridge.publish("framework/bridge", "agent-alpha", "update", "Keep me")
        malformed = self.root / "malformed.sqlite3"
        malformed.write_bytes(b"not a sqlite database")
        rollback = self.root / "unexpected-rollback.sqlite3"

        with self.assertRaisesRegex(BridgeError, "snapshot validation failed"):
            self.bridge.restore(malformed, rollback)

        self.assertFalse(rollback.exists())
        self.assertEqual(1, self.bridge.health()["counts"]["events"])

    def test_uncommitted_write_is_recovered_after_process_exit(self) -> None:
        script = "\n".join(
            [
                "import os, sys",
                f"sys.path.insert(0, {str(PROJECT_ROOT / 'src')!r})",
                "from cohestra.bridge.db import ConversationBridge",
                f"bridge = ConversationBridge({str(self.database)!r})",
                "connection = bridge._connect()",
                "connection.execute('BEGIN IMMEDIATE')",
                "connection.execute(\"INSERT INTO tasks VALUES('crash/test','Crash','agent-alpha','now','open')\")",
                "os._exit(23)",
            ]
        )
        completed = subprocess.run([sys.executable, "-B", "-c", script], check=False)
        self.assertEqual(23, completed.returncode)
        self.assertEqual(0, self.bridge.health()["counts"]["tasks"])

        created = self.bridge.create_task("recovered/test", "Recovered", "agent-alpha")
        self.assertEqual("recovered/test", created["task_id"])

    def test_cli_returns_machine_readable_json(self) -> None:
        cli_database = self.root / "cli.sqlite3"
        command = [
            sys.executable,
            "-m",
            "cohestra.bridge",
            "--db",
            str(cli_database),
            "init",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(7, payload["data"]["schema_version"])

    def test_cli_requires_an_explicit_database(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "cohestra.bridge", "health"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stderr)
        self.assertEqual("invalid_arguments", payload["error"]["code"])
        self.assertIn("--db", payload["error"]["message"])

    def test_cli_validation_error_is_machine_readable(self) -> None:
        command = [
            sys.executable,
            "-m",
            "cohestra.bridge",
            "--db",
            str(self.database),
            "publish",
            "--task-id",
            "missing/task",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual("invalid_arguments", payload["error"]["code"])

    def test_cli_output_is_always_utf8(self) -> None:
        command = [
            sys.executable,
            "-m",
            "cohestra.bridge",
            "--db",
            str(self.database),
            "task-create",
            "--task-id",
            "encoding/test",
            "--title",
            "中文交接验收",
            "--agent",
            "agent-alpha",
        ]
        completed = subprocess.run(command, check=False, capture_output=True)
        self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8"))
        payload = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual("中文交接验收", payload["data"]["title"])

    def test_cli_malformed_database_error_is_machine_readable(self) -> None:
        malformed = self.root / "malformed-cli.sqlite3"
        malformed.write_bytes(os.urandom(128))
        command = [
            sys.executable,
            "-m",
            "cohestra.bridge",
            "--db",
            str(malformed),
            "health",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(3, completed.returncode)
        payload = json.loads(completed.stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual("database_error", payload["error"]["code"])

    def test_concurrent_publishers_do_not_lose_events(self) -> None:
        self.bridge.create_task("concurrency/test", "Concurrent publishers", "agent-0")
        agents = [f"agent-{index}" for index in range(4)]
        for agent in agents[1:]:
            self.bridge.join_task("concurrency/test", agent, "agent-0")

        def publish(agent: str, sequence: int) -> str:
            event = self.bridge.publish(
                "concurrency/test",
                agent,
                "update",
                f"{agent} update {sequence}",
            )
            return event["event_uid"]

        event_uids = []
        for round_number in range(3):
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(publish, agent, round_number * 10 + sequence)
                    for agent in agents
                    for sequence in range(10)
                ]
                event_uids.extend(future.result() for future in futures)

        events = self.bridge.list_events(
            "concurrency/test",
            "agent-0",
            after_event_id=0,
            limit=200,
            include_own=True,
        )
        self.assertEqual(120, len(events))
        self.assertEqual(120, len(set(event_uids)))
        self.assertEqual("ok", self.bridge.health()["integrity"])

    def test_discovery_join_request_is_private_until_approved(self) -> None:
        self.bridge.create_task(
            "framework/private",
            "Private task title",
            "agent-alpha",
        )
        self.bridge.create_task(
            "framework/admission",
            "Agent admission",
            "agent-alpha",
            "request",
            "协作消息桥任务准入设计",
        )
        self.assertEqual([], self.bridge.discover_tasks("new-agent", "framework/private"))
        candidates = self.bridge.discover_tasks("new-agent", "消息桥")
        self.assertEqual(["framework/admission"], [item["task_id"] for item in candidates])
        self.assertEqual(
            {
                "task_id": "framework/admission",
                "title": "Agent admission",
                "status": "open",
                "discovery_summary": "协作消息桥任务准入设计",
                "join_policy": "request",
                "updated_at": candidates[0]["updated_at"],
            },
            candidates[0],
        )
        with self.assertRaisesRegex(BridgeError, "not a participant"):
            self.bridge.list_events("framework/admission", "new-agent")

        request = self.bridge.create_join_request(
            "framework/admission", "new-agent", "希望加入消息桥准入设计任务"
        )
        duplicate = self.bridge.create_join_request(
            "framework/admission", "new-agent", "重复提交不应产生第二条申请"
        )
        self.assertTrue(request["created"])
        self.assertFalse(duplicate["created"])
        self.assertEqual(request["request_uid"], duplicate["request_uid"])
        with self.assertRaisesRegex(BridgeError, "not a participant"):
            self.bridge.resolve_join_request(request["request_uid"], "new-agent", "approve")

        resolved = self.bridge.resolve_join_request(
            request["request_uid"], "agent-alpha", "approve", "身份与任务匹配"
        )
        self.assertEqual("approved", resolved["status"])
        self.assertTrue(resolved["joined"])
        self.assertEqual(
            "request",
            self.bridge.status("framework/admission", "new-agent")["participants"][1][
                "admission_method"
            ],
        )
        with self.assertRaisesRegex(BridgeError, "already"):
            self.bridge.create_join_request("framework/admission", "new-agent", "已经加入")
        with self.assertRaisesRegex(BridgeError, "already approved"):
            self.bridge.resolve_join_request(request["request_uid"], "agent-alpha", "deny")

    def test_broker_shutdown_status_requires_no_target_event_or_live_claim(
        self,
    ) -> None:
        self.bridge.create_task("broker/idle", "Broker idle", "agent-alpha")
        self.bridge.join_task("broker/idle", "agent-beta", "agent-alpha")
        event = self.bridge.publish(
            "broker/idle", "agent-alpha", "request", "Review", target_agent="agent-beta"
        )
        self.assertFalse(self.bridge.broker_shutdown_status(["agent-beta", "agent-alpha"])["ready"])
        wake_claim = self.bridge.claim_wake(
            "broker/idle",
            event["event_uid"],
            "agent-beta",
            "broker-test",
            str(uuid4()),
        )
        status = self.bridge.broker_shutdown_status(["agent-beta", "agent-alpha"])
        self.assertEqual(1, status["active_wake_claims"])
        self.assertFalse(status["ready"])
        self.bridge.finish_wake_claim(wake_claim["claim_uid"], "agent-beta", "dispatched")
        self.bridge.publish(
            "broker/idle",
            "agent-beta",
            "response",
            "Reviewed",
            reply_to_uid=event["event_uid"],
        )
        package_id = str(uuid4())
        self.bridge.claim_work(
            "broker/idle", "agent-alpha", "agent-beta", ["broker-test"], package_id
        )
        status = self.bridge.broker_shutdown_status(["agent-beta", "agent-alpha"])
        self.assertEqual(1, status["active_work_claims"])
        self.assertFalse(status["ready"])
        self.bridge.finish_work_claim(package_id, "agent-beta", "completed")
        self.assertTrue(self.bridge.broker_shutdown_status(["agent-beta", "agent-alpha"])["ready"])
        completed, payload = self._run_cli(
            "broker-shutdown-status", "--agent", "agent-beta", "--agent", "agent-alpha"
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(payload["data"]["ready"])

    def test_invitation_is_bound_one_time_and_does_not_expose_events(self) -> None:
        self._create_shared_task()
        invitation = self.bridge.create_invitation(
            "framework/bridge", "new-agent", "agent-beta", expires_in_minutes=10
        )
        with self.assertRaisesRegex(BridgeError, "another Agent"):
            self.bridge.redeem_invitation(invitation["token"], "other-agent")
        with self.assertRaisesRegex(BridgeError, "not a participant"):
            self.bridge.list_events("framework/bridge", "new-agent")
        joined = self.bridge.redeem_invitation(invitation["token"], "new-agent")
        self.assertEqual("invite", joined["admission_method"])
        with self.assertRaisesRegex(BridgeError, "already consumed"):
            self.bridge.redeem_invitation(invitation["token"], "new-agent")
        listed = self.bridge.list_invitations("framework/bridge", "agent-beta")
        self.assertIsNone(listed[0].get("token"))
        self.assertIsNotNone(listed[0]["consumed_at"])

    def test_manifest_lifecycle_requires_owner_and_cleans_pending_admission(
        self,
    ) -> None:
        self.bridge.create_task(
            "lifecycle/task",
            "Lifecycle",
            "agent-alpha",
            "request",
            "Lifecycle coordination",
            "Deliver an accepted lifecycle",
            ["Manifest is readable", "Closed tasks reject writes"],
            "worklogs/example.md",
        )
        self.bridge.join_task("lifecycle/task", "agent-beta", "agent-alpha")
        request = self.bridge.create_join_request(
            "lifecycle/task", "new-agent", "Need lifecycle access"
        )
        invitation = self.bridge.create_invitation("lifecycle/task", "invited-agent", "agent-alpha")

        with self.assertRaisesRegex(BridgeError, "not the owner"):
            self.bridge.set_task_manifest("lifecycle/task", "agent-beta", phase="blocked")
        updated = self.bridge.set_task_manifest(
            "lifecycle/task",
            "agent-alpha",
            objective="Finish lifecycle MVP",
            acceptance_criteria=["All lifecycle tests pass"],
            phase="blocked",
        )
        self.assertEqual("blocked", updated["phase"])
        self.assertEqual(["All lifecycle tests pass"], updated["acceptance_criteria"])

        closed = self.bridge.close_task(
            "lifecycle/task", "agent-alpha", "completed", "Acceptance passed"
        )
        self.assertEqual("completed", closed["phase"])
        self.assertEqual(
            "denied",
            self.bridge.get_join_request(request["request_uid"], "new-agent")["status"],
        )
        with self.assertRaisesRegex(BridgeError, "revoked"):
            self.bridge.redeem_invitation(invitation["token"], "invited-agent")
        with self.assertRaisesRegex(BridgeError, "closed"):
            self.bridge.publish("lifecycle/task", "agent-alpha", "update", "Closed write")

        reopened = self.bridge.reopen_task("lifecycle/task", "agent-alpha")
        self.assertEqual("active", reopened["phase"])
        self.bridge.close_task("lifecycle/task", "agent-alpha", "cancelled")
        archived = self.bridge.archive_task("lifecycle/task", "agent-alpha")
        self.assertEqual("archived", archived["phase"])
        with self.assertRaisesRegex(BridgeError, "archived"):
            self.bridge.reopen_task("lifecycle/task", "agent-alpha")

    def test_dashboard_summarizes_visible_work_without_mutating_cursors(self) -> None:
        self.bridge.create_task(
            "dashboard/task",
            "Dashboard",
            "agent-alpha",
            "request",
            "Dashboard coordination",
        )
        self.bridge.publish("dashboard/task", "agent-alpha", "request", "Review dashboard")
        self.bridge.join_task("dashboard/task", "agent-beta", "agent-alpha")
        self.bridge.create_join_request("dashboard/task", "new-agent", "Request dashboard access")

        before = self.bridge.status("dashboard/task", "agent-beta")["last_read_event_id"]
        dashboard = self.bridge.dashboard("agent-beta")
        after = self.bridge.status("dashboard/task", "agent-beta")["last_read_event_id"]
        self.assertEqual(before, after)
        self.assertEqual(1, dashboard["summary"]["visible_tasks"])
        self.assertEqual(1, dashboard["summary"]["unread_events"])
        self.assertEqual(1, dashboard["summary"]["pending_join_requests"])
        self.assertEqual(1, dashboard["tasks"][0]["unread"])
        self.assertEqual("Dashboard", dashboard["tasks"][0]["objective"])

    def test_leader_view_derives_request_state_without_mutating_cursors(self) -> None:
        self._create_shared_task()
        self.bridge.join_task("framework/bridge", "agent-gamma", "agent-alpha")

        answered = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Review architecture",
            target_agent="agent-beta",
        )
        self.bridge.acknowledge(answered["event_uid"], "agent-beta")
        first_response = self.bridge.publish(
            "framework/bridge",
            "agent-beta",
            "response",
            "Short conclusion",
            reply_to_uid=answered["event_uid"],
        )
        second_response = self.bridge.publish(
            "framework/bridge",
            "agent-beta",
            "response",
            "Full conclusion",
            details="Complete review body",
            reply_to_uid=answered["event_uid"],
        )

        active = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Active wake",
            target_agent="agent-gamma",
        )
        self.bridge.claim_wake(
            "framework/bridge",
            active["event_uid"],
            "agent-gamma",
            "agent-gamma-headless",
            str(uuid4()),
        )

        failed = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Failed wake",
            target_agent="agent-gamma",
        )
        failed_claim = self.bridge.claim_wake(
            "framework/bridge",
            failed["event_uid"],
            "agent-gamma",
            "agent-gamma-headless",
            str(uuid4()),
        )
        self.bridge.finish_wake_claim(
            failed_claim["claim_uid"], "agent-gamma", "launch_failed", "spawn_error"
        )

        overdue = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Overdue request",
            target_agent="agent-beta",
        )
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE events SET created_at = '2000-01-01T00:00:00Z' WHERE event_uid = ?",
            (overdue["event_uid"],),
        )
        connection.commit()
        connection.close()

        cursor_before = self.bridge.status("framework/bridge", "agent-alpha")["last_read_event_id"]
        view = self.bridge.leader_view("framework/bridge", "agent-alpha", stale_after_seconds=1)
        replay = self.bridge.leader_view("framework/bridge", "agent-alpha", stale_after_seconds=1)
        cursor_after = self.bridge.status("framework/bridge", "agent-alpha")["last_read_event_id"]

        self.assertEqual(cursor_before, cursor_after)
        self.assertEqual(view["requests"], replay["requests"])
        self.assertEqual(view["summary"], replay["summary"])
        self.assertEqual(4, view["summary"]["requests"])
        self.assertEqual(1, view["summary"]["answered"])
        self.assertEqual(1, view["summary"]["processing"])
        self.assertEqual(1, view["summary"]["failed"])
        self.assertEqual(1, view["summary"]["overdue"])
        self.assertEqual(1, view["summary"]["duplicate_response_threads"])

        by_uid = {item["request"]["event_uid"]: item for item in view["requests"]}
        answered_state = by_uid[answered["event_uid"]]
        self.assertEqual("review", answered_state["user_attention"])
        self.assertEqual(2, answered_state["response_count"])
        self.assertEqual(1, answered_state["duplicate_response_count"])
        self.assertEqual(
            [first_response["event_uid"], second_response["event_uid"]],
            [item["event_uid"] for item in answered_state["responses"]],
        )
        self.assertEqual("Complete review body", answered_state["responses"][1]["details"])
        self.assertEqual("wake_claim_active", by_uid[active["event_uid"]]["reason"])
        self.assertEqual("required", by_uid[failed["event_uid"]]["user_attention"])
        self.assertEqual("overdue", by_uid[overdue["event_uid"]]["state"])

        with self.assertRaisesRegex(BridgeError, "current task leader"):
            self.bridge.leader_view("framework/bridge", "agent-beta")

    def test_cli_leader_view_filters_by_event_id(self) -> None:
        cli_database = self.root / "leader-view.sqlite3"
        self._run_cli("init", database=cli_database)
        self._run_cli(
            "task-create",
            "--task-id",
            "cli/leader-view",
            "--title",
            "Leader view",
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        _, first = self._run_cli(
            "publish",
            "--task-id",
            "cli/leader-view",
            "--agent",
            "agent-alpha",
            "--kind",
            "request",
            "--summary",
            "Old request",
            database=cli_database,
        )
        self._run_cli(
            "publish",
            "--task-id",
            "cli/leader-view",
            "--agent",
            "agent-alpha",
            "--kind",
            "request",
            "--summary",
            "Current request",
            database=cli_database,
        )
        completed, payload = self._run_cli(
            "leader-view",
            "--task-id",
            "cli/leader-view",
            "--agent",
            "agent-alpha",
            "--after",
            str(first["data"]["event_id"]),
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(1, payload["data"]["summary"]["requests"])
        self.assertEqual("Current request", payload["data"]["requests"][0]["request"]["summary"])

    def test_native_cli_preserves_multiline_details_and_routing(self) -> None:
        cli_database = self.root / "native-multiline.sqlite3"
        self._run_cli("init", database=cli_database)
        self._run_cli(
            "task-create",
            "--task-id",
            "cli/native-multiline",
            "--title",
            "Native multiline transport",
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        self._run_cli(
            "task-join",
            "--task-id",
            "cli/native-multiline",
            "--agent",
            "agent-beta",
            "--requested-by",
            "agent-alpha",
            database=cli_database,
        )

        details = "first line\nsecond line\nthird line"
        evidence = str(self.root / "evidence with spaces.md")
        completed, request = self._run_cli(
            "publish",
            "--task-id",
            "cli/native-multiline",
            "--agent",
            "agent-alpha",
            "--kind",
            "request",
            "--summary",
            "Preserve structured arguments",
            "--details",
            details,
            "--target-agent",
            "agent-beta",
            "--evidence",
            evidence,
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

        _, read_request = self._run_cli(
            "read",
            "--event",
            request["data"]["event_uid"],
            "--agent",
            "agent-beta",
            database=cli_database,
        )
        self.assertEqual(details, read_request["data"]["details"])
        self.assertEqual("agent-beta", read_request["data"]["target_agent"])
        self.assertEqual([evidence], read_request["data"]["evidence"])

        completed, response = self._run_cli(
            "publish",
            "--task-id",
            "cli/native-multiline",
            "--agent",
            "agent-beta",
            "--kind",
            "response",
            "--summary",
            "Native response",
            "--details",
            details,
            "--reply-to",
            request["data"]["event_uid"],
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

        _, read_response = self._run_cli(
            "read",
            "--event",
            response["data"]["event_uid"],
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        self.assertEqual(details, read_response["data"]["details"])
        self.assertEqual(request["data"]["event_uid"], read_response["data"]["reply_to_uid"])

    def test_concurrent_join_requests_and_resolutions_are_idempotent(self) -> None:
        self.bridge.create_task(
            "concurrency/admission",
            "Admission concurrency",
            "agent-alpha",
            "request",
        )

        def request_access(_: int) -> dict:
            return self.bridge.create_join_request(
                "concurrency/admission", "new-agent", "Concurrent request"
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            requests = list(executor.map(request_access, range(16)))
        self.assertEqual(1, sum(1 for item in requests if item["created"]))
        self.assertEqual(1, len({item["request_uid"] for item in requests}))
        request_uid = requests[0]["request_uid"]

        def resolve(_: int) -> str:
            try:
                self.bridge.resolve_join_request(request_uid, "agent-alpha", "approve")
                return "approved"
            except BridgeError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(resolve, range(2)))
        self.assertCountEqual(["approved", "join_request_resolved"], outcomes)
        self.assertEqual(
            "active",
            self.bridge.get_task_manifest("concurrency/admission", "new-agent")["phase"],
        )

    def test_cli_admission_manifest_dashboard_and_close_workflow(self) -> None:
        cli_database = self.root / "cli-lifecycle.sqlite3"
        completed, payload = self._run_cli("init", database=cli_database)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(7, payload["data"]["schema_version"])

        completed, created = self._run_cli(
            "task-create",
            "--task-id",
            "cli/workflow",
            "--title",
            "CLI workflow",
            "--agent",
            "agent-alpha",
            "--join-policy",
            "request",
            "--discovery-summary",
            "CLI admission workflow",
            "--objective",
            "Exercise the complete CLI workflow",
            "--acceptance-criterion",
            "New Agent can join",
            "--worklog-path",
            "worklogs/example.md",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("active", created["data"]["phase"])

        _, discovered = self._run_cli(
            "task-discover",
            "--agent",
            "new-agent",
            "--query",
            "CLI admission",
            database=cli_database,
        )
        self.assertEqual("cli/workflow", discovered["data"]["tasks"][0]["task_id"])
        _, requested = self._run_cli(
            "join-request",
            "--task-id",
            "cli/workflow",
            "--agent",
            "new-agent",
            "--message",
            "Join the CLI workflow",
            database=cli_database,
        )
        request_uid = requested["data"]["request_uid"]
        _, pending = self._run_cli(
            "join-requests",
            "--task-id",
            "cli/workflow",
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        self.assertEqual(request_uid, pending["data"]["requests"][0]["request_uid"])
        completed, _ = self._run_cli(
            "join-request-resolve",
            "--request-id",
            request_uid,
            "--agent",
            "agent-alpha",
            "--decision",
            "approve",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        _, dashboard = self._run_cli("dashboard", "--agent", "new-agent", database=cli_database)
        self.assertEqual(1, dashboard["data"]["summary"]["visible_tasks"])
        self.assertEqual(
            "Exercise the complete CLI workflow",
            dashboard["data"]["tasks"][0]["objective"],
        )
        completed, closed = self._run_cli(
            "task-close",
            "--task-id",
            "cli/workflow",
            "--agent",
            "agent-alpha",
            "--phase",
            "completed",
            "--reason",
            "CLI acceptance passed",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("completed", closed["data"]["phase"])

    def test_v1_health_snapshot_and_restore_migrate_without_data_loss(self) -> None:
        legacy = self.root / "legacy.sqlite3"
        connection = sqlite3.connect(legacy)
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY, title TEXT NOT NULL, created_by TEXT NOT NULL,
                created_at TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE TABLE participants (
                task_id TEXT NOT NULL, agent_id TEXT NOT NULL, joined_at TEXT NOT NULL,
                last_read_event_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(task_id, agent_id)
            );
            CREATE TABLE events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_uid TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL, source_agent TEXT NOT NULL, kind TEXT NOT NULL,
                summary TEXT NOT NULL, details TEXT, reply_to_uid TEXT,
                evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE acknowledgements (
                event_id INTEGER NOT NULL, agent_id TEXT NOT NULL,
                acknowledged_at TEXT NOT NULL, PRIMARY KEY(event_id, agent_id)
            );
            INSERT INTO schema_meta VALUES ('schema_version', '1');
            INSERT INTO tasks VALUES ('legacy/task', 'Legacy', 'agent-alpha', '2026-01-01T00:00:00Z', 'open');
            INSERT INTO participants(task_id, agent_id, joined_at) VALUES
                ('legacy/task', 'agent-alpha', '2026-01-01T00:00:00Z');
            """
        )
        connection.commit()
        connection.close()

        legacy_bridge = ConversationBridge(legacy)
        self.assertTrue(legacy_bridge.health()["migration_required"])
        legacy_snapshot = self.root / "legacy-snapshot.sqlite3"
        legacy_bridge.snapshot(legacy_snapshot)
        legacy_bridge.initialize()
        self.assertEqual(7, legacy_bridge.health()["schema_version"])
        self.assertEqual(
            "private",
            legacy_bridge.status("legacy/task", "agent-alpha")["access"]["join_policy"],
        )

        live = self.root / "live.sqlite3"
        live_bridge = ConversationBridge(live)
        live_bridge.initialize()
        live_bridge.create_task("replacement", "Replacement", "agent-alpha")
        result = live_bridge.restore(legacy_snapshot, self.root / "rollback.sqlite3")
        self.assertEqual(1, result["snapshot_health"]["schema_version"])
        self.assertEqual(7, result["health"]["schema_version"])
        self.assertEqual(1, live_bridge.health()["counts"]["tasks"])

    def test_leadership_transfer_and_targeted_event_visibility(self) -> None:
        self._create_shared_task()
        self.bridge.join_task("framework/bridge", "agent-gamma", "agent-alpha")
        initial = self.bridge.get_task_leadership("framework/bridge", "agent-beta")
        self.assertEqual(("agent-alpha", 1), (initial["leader_agent"], initial["epoch"]))
        leader_event = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Leader request",
            target_agent="agent-beta",
        )
        self.assertEqual(1, leader_event["leader_epoch"])
        self.assertEqual("agent-beta", leader_event["target_agent"])
        self.assertEqual([], self.bridge.list_events("framework/bridge", "agent-gamma"))
        with self.assertRaisesRegex(BridgeError, "targeted to another"):
            self.bridge.read_event(leader_event["event_uid"], "agent-gamma")
        with self.assertRaisesRegex(BridgeError, "not a participant"):
            self.bridge.publish(
                "framework/bridge", "agent-alpha", "request", "No", target_agent="other-agent"
            )
        with self.assertRaisesRegex(BridgeError, "neither the leader nor owner"):
            self.bridge.transfer_task_leadership("framework/bridge", "agent-gamma", "agent-beta")
        moved = self.bridge.transfer_task_leadership(
            "framework/bridge", "agent-alpha", "agent-beta"
        )
        self.assertEqual(("agent-beta", 2), (moved["leader_agent"], moved["epoch"]))
        # The owner is retained as an emergency handoff authority.
        restored = self.bridge.transfer_task_leadership(
            "framework/bridge", "agent-alpha", "agent-gamma"
        )
        self.assertEqual(("agent-gamma", 3), (restored["leader_agent"], restored["epoch"]))
        stale = self.bridge.publish("framework/bridge", "agent-beta", "handoff", "Old leader event")
        self.assertIsNone(stale["leader_epoch"])
        current = self.bridge.publish(
            "framework/bridge", "agent-gamma", "handoff", "Current leader event"
        )
        self.assertEqual(3, current["leader_epoch"])

    def test_leader_lease_is_observation_only_and_epoch_fenced(self) -> None:
        self._create_shared_task()
        event = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Lease observation invariant",
            target_agent="agent-beta",
        )
        connection = sqlite3.connect(self.database)
        cursor_before = connection.execute(
            "SELECT last_read_event_id FROM participants WHERE task_id = ? AND agent_id = ?",
            ("framework/bridge", "agent-beta"),
        ).fetchone()[0]
        event_count_before = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        ack_count_before = connection.execute("SELECT COUNT(*) FROM acknowledgements").fetchone()[0]
        connection.close()

        self.assertEqual(
            "not_renewed",
            self.bridge.get_leader_observation("framework/bridge", "agent-beta")["state"],
        )
        with self.assertRaisesRegex(BridgeError, "current task leader"):
            self.bridge.leader_view("framework/bridge", "agent-beta")
        renewed = self.bridge.renew_leader_lease(
            "framework/bridge", "agent-alpha", 1, lease_seconds=30
        )
        self.assertEqual("healthy", renewed["state"])
        self.assertEqual(
            "healthy",
            self.bridge.get_leader_observation("framework/bridge", "agent-beta")["state"],
        )
        leadership_before = self.bridge.get_task_leadership("framework/bridge", "agent-alpha")

        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE leader_leases SET lease_expires_at = '2000-01-01T00:00:00Z' WHERE task_id = ?",
            ("framework/bridge",),
        )
        connection.commit()
        connection.close()
        self.assertEqual(
            "leader_unresponsive",
            self.bridge.get_leader_observation("framework/bridge", "agent-beta")["state"],
        )
        # A late renewal in the same epoch restores only the observation row.
        self.bridge.renew_leader_lease("framework/bridge", "agent-alpha", 1, 30)
        self.assertEqual(
            leadership_before,
            self.bridge.get_task_leadership("framework/bridge", "agent-alpha"),
        )

        moved = self.bridge.transfer_task_leadership(
            "framework/bridge", "agent-alpha", "agent-beta"
        )
        self.assertEqual(2, moved["epoch"])
        self.assertEqual(
            "not_renewed",
            self.bridge.get_leader_observation("framework/bridge", "agent-alpha")["state"],
        )
        with self.assertRaisesRegex(BridgeError, "leader_epoch") as stale:
            self.bridge.renew_leader_lease("framework/bridge", "agent-alpha", 1, 30)
        self.assertEqual("stale_leader_epoch", stale.exception.code)

        connection = sqlite3.connect(self.database)
        self.assertEqual(
            cursor_before,
            connection.execute(
                "SELECT last_read_event_id FROM participants WHERE task_id = ? AND agent_id = ?",
                ("framework/bridge", "agent-beta"),
            ).fetchone()[0],
        )
        self.assertEqual(
            event_count_before,
            connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        )
        self.assertEqual(
            ack_count_before,
            connection.execute("SELECT COUNT(*) FROM acknowledgements").fetchone()[0],
        )
        connection.close()
        self.assertEqual(
            event["event_uid"],
            self.bridge.read_event(event["event_uid"], "agent-beta")["event_uid"],
        )

    def test_escalation_validation_deduplication_and_resolution(self) -> None:
        self._create_shared_task()
        with self.assertRaisesRegex(BridgeError, "incident_type"):
            self.bridge.open_escalation(
                "framework/bridge", "agent-beta", 1, "raw_prompt", "event:secret"
            )
        with self.assertRaisesRegex(BridgeError, "incident_key"):
            self.bridge.open_escalation(
                "framework/bridge",
                "agent-beta",
                1,
                "response_missing",
                "the user needs to inspect this",
            )
        with self.assertRaisesRegex(BridgeError, "absolute path"):
            self.bridge.open_escalation(
                "framework/bridge",
                "agent-beta",
                1,
                "response_missing",
                f"event:{uuid4()}",
                evidence_pointer="C:/private/prompt.txt",
            )

        incident_key = f"wake_claim:{uuid4()}"
        before = self.bridge.health()["counts"]
        first = self.bridge.open_escalation(
            "framework/bridge",
            "agent-beta",
            1,
            "wake_claim_failed",
            incident_key,
            affected_agent="agent-beta",
            evidence_pointer="collaboration-design/evidence.md",
        )
        replay = self.bridge.open_escalation(
            "framework/bridge", "agent-beta", 1, "wake_claim_failed", incident_key
        )
        after = self.bridge.health()["counts"]
        self.assertTrue(first["should_notify"])
        self.assertFalse(replay["should_notify"])
        self.assertEqual(first["escalation_uid"], replay["escalation_uid"])
        self.assertEqual("inspect_wake_claim", first["action_code"])
        self.assertNotIn("summary", first)
        self.assertNotIn("details", first)
        self.assertEqual(before["events"], after["events"])
        self.assertEqual(before["acknowledgements"], after["acknowledgements"])

        with self.assertRaisesRegex(BridgeError, "resolution_code"):
            self.bridge.resolve_escalation(first["escalation_uid"], "agent-alpha", "task_closed")
        resolved = self.bridge.resolve_escalation(
            first["escalation_uid"], "agent-alpha", "resolved"
        )
        self.assertEqual("resolved", resolved["state"])
        after_resolution = self.bridge.open_escalation(
            "framework/bridge", "agent-beta", 1, "wake_claim_failed", incident_key
        )
        self.assertFalse(after_resolution["should_notify"])
        self.assertEqual("resolved", after_resolution["state"])
        new_incident = self.bridge.open_escalation(
            "framework/bridge",
            "agent-beta",
            1,
            "wake_claim_failed",
            f"wake_claim:{uuid4()}",
        )
        self.assertTrue(new_incident["should_notify"])

    def test_concurrent_escalation_open_notifies_once(self) -> None:
        self._create_shared_task()
        incident_key = f"event:{uuid4()}"

        def report(_: int) -> dict:
            return ConversationBridge(self.database).open_escalation(
                "framework/bridge",
                "agent-beta",
                1,
                "response_missing",
                incident_key,
            )

        with ThreadPoolExecutor(max_workers=16) as executor:
            outcomes = list(executor.map(report, range(16)))
        self.assertEqual(1, sum(bool(item["should_notify"]) for item in outcomes))
        self.assertEqual(1, len({item["escalation_uid"] for item in outcomes}))
        self.assertEqual(
            1,
            len(self.bridge.list_escalations("framework/bridge", "agent-alpha", "open")),
        )

    def test_escalation_authority_transfer_and_task_close(self) -> None:
        self._create_shared_task()
        self.bridge.join_task("framework/bridge", "agent-gamma", "agent-alpha")
        self.bridge.transfer_task_leadership("framework/bridge", "agent-alpha", "agent-beta")
        self.bridge.transfer_task_leadership("framework/bridge", "agent-beta", "agent-gamma")
        escalation = self.bridge.open_escalation(
            "framework/bridge",
            "agent-beta",
            3,
            "work_claim_expired",
            f"work_package:{uuid4()}",
            affected_agent="agent-beta",
        )
        with self.assertRaisesRegex(BridgeError, "neither the current leader nor owner"):
            self.bridge.resolve_escalation(escalation["escalation_uid"], "agent-beta")
        self.assertEqual(
            "resolved",
            self.bridge.resolve_escalation(escalation["escalation_uid"], "agent-gamma")["state"],
        )
        still_open = self.bridge.open_escalation(
            "framework/bridge",
            "agent-beta",
            3,
            "acknowledgement_missing",
            f"event:{uuid4()}",
        )
        self.bridge.renew_leader_lease("framework/bridge", "agent-gamma", 3, 30)
        self.bridge.close_task("framework/bridge", "agent-alpha", "cancelled")
        closed = self.bridge.get_escalation(still_open["escalation_uid"], "agent-beta")
        self.assertEqual(("resolved", "task_closed"), (closed["state"], closed["resolution_code"]))
        self.assertEqual(
            "not_renewed",
            self.bridge.get_leader_observation("framework/bridge", "agent-beta")["state"],
        )

    def test_wake_claim_is_idempotent_and_does_not_acknowledge(self) -> None:
        self._create_shared_task()
        event = self.bridge.publish(
            "framework/bridge", "agent-alpha", "request", "Wake Claude", target_agent="agent-beta"
        )
        before = self.bridge.status("framework/bridge", "agent-beta")
        attempt_id = str(uuid4())
        claim = self.bridge.claim_wake(
            "framework/bridge",
            event["event_uid"],
            "agent-beta",
            "agent-beta-headless",
            attempt_id,
        )
        replay = self.bridge.claim_wake(
            "framework/bridge",
            event["event_uid"],
            "agent-beta",
            "agent-beta-headless",
            attempt_id,
        )
        after = self.bridge.status("framework/bridge", "agent-beta")
        self.assertEqual(claim["claim_uid"], replay["claim_uid"])
        self.assertEqual("claimed", claim["state"])
        self.assertEqual(before["last_read_event_id"], after["last_read_event_id"])
        self.assertEqual(before["unread"], after["unread"])
        connection = sqlite3.connect(self.database)
        acknowledgements = connection.execute("SELECT COUNT(*) FROM acknowledgements").fetchone()[0]
        connection.close()
        self.assertEqual(0, acknowledgements)
        finished = self.bridge.finish_wake_claim(claim["claim_uid"], "agent-beta", "dispatched")
        self.assertEqual("dispatched", finished["state"])
        self.assertEqual(1, self.bridge.status("framework/bridge", "agent-beta")["unread"])

    def test_wake_claim_serializes_concurrent_attempts(self) -> None:
        self._create_shared_task()
        event = self.bridge.publish(
            "framework/bridge", "agent-alpha", "handoff", "Wake once", target_agent="agent-beta"
        )

        def claim_once(_: int) -> str:
            try:
                return self.bridge.claim_wake(
                    "framework/bridge",
                    event["event_uid"],
                    "agent-beta",
                    "agent-beta-headless",
                    str(uuid4()),
                )["state"]
            except BridgeError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(claim_once, range(8)))
        self.assertEqual(1, outcomes.count("claimed"))
        self.assertEqual(7, outcomes.count("wake_already_claimed"))

    def test_wake_claim_fences_leadership_at_claim_time(self) -> None:
        self._create_shared_task()
        event_before_transfer = self.bridge.publish(
            "framework/bridge", "agent-alpha", "request", "Stale wake", target_agent="agent-beta"
        )
        self.bridge.transfer_task_leadership("framework/bridge", "agent-alpha", "agent-beta")
        with self.assertRaisesRegex(BridgeError, "current task leader"):
            self.bridge.claim_wake(
                "framework/bridge",
                event_before_transfer["event_uid"],
                "agent-beta",
                "agent-beta-headless",
                str(uuid4()),
            )

        event_after_transfer = self.bridge.publish(
            "framework/bridge",
            "agent-beta",
            "handoff",
            "Current wake",
            target_agent="agent-alpha",
        )
        claim = self.bridge.claim_wake(
            "framework/bridge",
            event_after_transfer["event_uid"],
            "agent-alpha",
            "agent-alpha-ui",
            str(uuid4()),
        )
        self.bridge.transfer_task_leadership("framework/bridge", "agent-alpha", "agent-alpha")
        # Claim is the authorization linearization point: later transfer cannot
        # revoke a dispatch that may already have reached a process or UI.
        self.assertEqual(
            "dispatched",
            self.bridge.finish_wake_claim(claim["claim_uid"], "agent-alpha", "dispatched")["state"],
        )

    def test_wake_claim_rejects_wrong_target_kind_and_agent(self) -> None:
        self._create_shared_task()
        self.bridge.join_task("framework/bridge", "agent-gamma", "agent-alpha")
        targeted = self.bridge.publish(
            "framework/bridge", "agent-alpha", "request", "Claude only", target_agent="agent-beta"
        )
        with self.assertRaisesRegex(BridgeError, "not the event target"):
            self.bridge.claim_wake(
                "framework/bridge",
                targeted["event_uid"],
                "agent-gamma",
                "agent-gamma-ui",
                str(uuid4()),
            )
        update = self.bridge.publish(
            "framework/bridge", "agent-alpha", "update", "No wake", target_agent="agent-beta"
        )
        with self.assertRaisesRegex(BridgeError, "request or handoff"):
            self.bridge.claim_wake(
                "framework/bridge",
                update["event_uid"],
                "agent-beta",
                "agent-beta-headless",
                str(uuid4()),
            )
        with self.assertRaisesRegex(BridgeError, "adapter_id"):
            self.bridge.claim_wake(
                "framework/bridge",
                targeted["event_uid"],
                "agent-beta",
                "bad adapter",
                str(uuid4()),
            )
        claim = self.bridge.claim_wake(
            "framework/bridge",
            targeted["event_uid"],
            "agent-beta",
            "agent-beta-headless",
            str(uuid4()),
        )
        with self.assertRaisesRegex(BridgeError, "result_code"):
            self.bridge.finish_wake_claim(
                claim["claim_uid"], "agent-beta", "launch_failed", "token=not-a-stable-code"
            )
        with self.assertRaisesRegex(BridgeError, "belongs to another claimer"):
            self.bridge.finish_wake_claim(claim["claim_uid"], "agent-gamma", "dispatched")

    def test_wake_claim_lease_and_explicit_launch_failure_retry(self) -> None:
        self._create_shared_task()
        failed_event = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Retry after launch failure",
            target_agent="agent-beta",
        )
        failed_claim = self.bridge.claim_wake(
            "framework/bridge",
            failed_event["event_uid"],
            "agent-beta",
            "agent-beta-headless",
            str(uuid4()),
        )
        self.bridge.finish_wake_claim(
            failed_claim["claim_uid"], "agent-beta", "launch_failed", "spawn_error"
        )
        with self.assertRaisesRegex(BridgeError, "explicit retry_claim_id"):
            self.bridge.claim_wake(
                "framework/bridge",
                failed_event["event_uid"],
                "agent-beta",
                "agent-beta-headless",
                str(uuid4()),
            )
        retry = self.bridge.claim_wake(
            "framework/bridge",
            failed_event["event_uid"],
            "agent-beta",
            "agent-beta-headless",
            str(uuid4()),
            retry_claim_uid=failed_claim["claim_uid"],
        )
        self.assertEqual(failed_claim["claim_uid"], retry["supersedes_claim_uid"])

        expired_event = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "handoff",
            "Lease expiry",
            target_agent="agent-beta",
        )
        expired_attempt = str(uuid4())
        expired_claim = self.bridge.claim_wake(
            "framework/bridge",
            expired_event["event_uid"],
            "agent-beta",
            "agent-beta-headless",
            expired_attempt,
            1,
        )
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE wake_claims SET lease_expires_at = '2000-01-01T00:00:00Z' WHERE claim_uid = ?",
            (expired_claim["claim_uid"],),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(BridgeError, "requires a new leader event"):
            self.bridge.claim_wake(
                "framework/bridge",
                expired_event["event_uid"],
                "agent-beta",
                "agent-beta-headless",
                expired_attempt,
            )
        with self.assertRaisesRegex(BridgeError, "expired before finish"):
            self.bridge.finish_wake_claim(expired_claim["claim_uid"], "agent-beta", "dispatched")

    def test_work_claims_are_atomic_idempotent_and_released_on_close(self) -> None:
        self._create_shared_task()
        self.bridge.join_task("framework/bridge", "agent-gamma", "agent-alpha")
        package_id = str(uuid4())
        claimed = self.bridge.claim_work(
            "framework/bridge",
            "agent-alpha",
            "agent-beta",
            ["bridge/core", "bridge/tests"],
            package_id,
        )
        replay = self.bridge.claim_work(
            "framework/bridge",
            "agent-alpha",
            "agent-beta",
            ["bridge/tests", "bridge/core"],
            package_id,
        )
        self.assertEqual(claimed, replay)
        self.assertEqual("claimed", claimed["state"])
        self.assertEqual(["bridge/core", "bridge/tests"], claimed["resources"])

        conflicting_package = str(uuid4())
        with self.assertRaisesRegex(BridgeError, "already claimed"):
            self.bridge.claim_work(
                "framework/bridge",
                "agent-alpha",
                "agent-gamma",
                ["bridge/docs", "bridge/core"],
                conflicting_package,
            )
        with self.assertRaisesRegex(BridgeError, "does not exist"):
            self.bridge.get_work_claim(conflicting_package, "agent-alpha")
        independent = self.bridge.claim_work(
            "framework/bridge",
            "agent-alpha",
            "agent-gamma",
            ["bridge/docs"],
            str(uuid4()),
        )
        self.assertEqual("claimed", independent["state"])

        completed = self.bridge.finish_work_claim(
            package_id, "agent-beta", "completed", "tests_passed"
        )
        self.assertEqual("completed", completed["state"])
        self.assertEqual(
            completed,
            self.bridge.finish_work_claim(package_id, "agent-beta", "completed", "tests_passed"),
        )

        close_package = str(uuid4())
        self.bridge.claim_work(
            "framework/bridge",
            "agent-alpha",
            "agent-beta",
            ["bridge/release-on-close"],
            close_package,
        )
        self.bridge.close_task("framework/bridge", "agent-alpha", "completed")
        released = self.bridge.get_work_claim(close_package, "agent-beta")
        self.assertEqual("released", released["state"])
        self.assertEqual("task_closed", released["result_code"])

    def test_work_claim_takeover_requires_explicit_expired_package(self) -> None:
        self._create_shared_task()
        self.bridge.join_task("framework/bridge", "agent-gamma", "agent-alpha")
        expired_package = str(uuid4())
        self.bridge.claim_work(
            "framework/bridge",
            "agent-alpha",
            "agent-beta",
            ["bridge/shared-module"],
            expired_package,
        )
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE work_claims SET lease_expires_at = '2000-01-01T00:00:00Z' WHERE package_uid = ?",
            (expired_package,),
        )
        connection.commit()
        connection.close()

        replacement_id = str(uuid4())
        with self.assertRaisesRegex(BridgeError, "explicit takeover_package_id"):
            self.bridge.claim_work(
                "framework/bridge",
                "agent-alpha",
                "agent-gamma",
                ["bridge/shared-module"],
                replacement_id,
            )
        replacement = self.bridge.claim_work(
            "framework/bridge",
            "agent-alpha",
            "agent-gamma",
            ["bridge/shared-module"],
            replacement_id,
            takeover_package_uid=expired_package,
        )
        self.assertEqual(expired_package, replacement["supersedes_package_uid"])
        self.assertEqual(
            "expired_unknown",
            self.bridge.get_work_claim(expired_package, "agent-beta")["state"],
        )
        self.assertEqual("claimed", replacement["state"])

        with self.assertRaisesRegex(BridgeError, "current task leader"):
            self.bridge.claim_work(
                "framework/bridge",
                "agent-beta",
                "agent-beta",
                ["bridge/other"],
                str(uuid4()),
            )
        for invalid in (r"C:\private", "../private", "Bridge/Uppercase"):
            with self.assertRaisesRegex(BridgeError, "logical identifier"):
                self.bridge.claim_work(
                    "framework/bridge",
                    "agent-alpha",
                    "agent-beta",
                    [invalid],
                    str(uuid4()),
                )

    def test_concurrent_work_claims_serialize_overlapping_resources(self) -> None:
        self._create_shared_task()
        self.bridge.join_task("framework/bridge", "agent-gamma", "agent-alpha")

        def claim(worker: str) -> str:
            try:
                return self.bridge.claim_work(
                    "framework/bridge",
                    "agent-alpha",
                    worker,
                    ["bridge/concurrent"],
                    str(uuid4()),
                )["state"]
            except BridgeError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(claim, ("agent-beta", "agent-gamma")))
        self.assertCountEqual(["claimed", "work_resource_claimed"], outcomes)

    def test_v6_migration_preserves_events_cursors_and_claims(self) -> None:
        self._create_shared_task()
        event = self.bridge.publish(
            "framework/bridge",
            "agent-alpha",
            "request",
            "Preserve v6 state",
            target_agent="agent-beta",
        )
        wake_claim = self.bridge.claim_wake(
            "framework/bridge",
            event["event_uid"],
            "agent-beta",
            "test-adapter",
            str(uuid4()),
        )
        self.bridge.finish_wake_claim(wake_claim["claim_uid"], "agent-beta", "dispatched")
        self.bridge.acknowledge(event["event_uid"], "agent-beta")
        package_uid = str(uuid4())
        self.bridge.claim_work(
            "framework/bridge",
            "agent-alpha",
            "agent-beta",
            ["bridge/schema"],
            package_uid,
        )
        cursor_before = self.bridge.status("framework/bridge", "agent-beta")["last_read_event_id"]
        counts_before = self.bridge.health()["counts"]

        connection = sqlite3.connect(self.database)
        connection.execute("DROP TABLE escalations")
        connection.execute("DROP TABLE leader_leases")
        connection.execute("UPDATE schema_meta SET value = '6' WHERE key = 'schema_version'")
        connection.commit()
        connection.close()
        legacy = ConversationBridge(self.database)
        legacy_health = legacy.health()
        self.assertEqual(
            (6, True),
            (legacy_health["schema_version"], legacy_health["migration_required"]),
        )
        with self.assertRaisesRegex(BridgeError, "requires init migration"):
            legacy.get_task_leadership("framework/bridge", "agent-alpha")
        self.assertEqual(6, legacy.health()["schema_version"])

        v6_snapshot = self.root / "v6-snapshot.sqlite3"
        legacy.snapshot(v6_snapshot)
        migrated = legacy.initialize()
        self.assertEqual((6, 7), (migrated["migrated_from"], migrated["schema_version"]))
        health = legacy.health(allow_legacy=False)
        self.assertEqual(
            (7, "wal", "ok"),
            (health["schema_version"], health["journal_mode"], health["integrity"]),
        )
        for table in (
            "tasks",
            "participants",
            "events",
            "acknowledgements",
            "wake_claims",
            "work_claims",
        ):
            self.assertEqual(counts_before[table], health["counts"][table])
        self.assertEqual(
            cursor_before,
            legacy.status("framework/bridge", "agent-beta")["last_read_event_id"],
        )
        self.assertEqual(
            "dispatched",
            legacy.get_wake_claim(wake_claim["claim_uid"], "agent-beta")["state"],
        )
        self.assertEqual("claimed", legacy.get_work_claim(package_uid, "agent-beta")["state"])

        replacement_database = self.root / "replacement-v7.sqlite3"
        replacement = ConversationBridge(replacement_database)
        replacement.initialize()
        replacement.create_task("replacement/task", "Replacement", "agent-alpha")
        restored = replacement.restore(v6_snapshot, self.root / "replacement-rollback.sqlite3")
        self.assertEqual(
            (6, 7),
            (
                restored["snapshot_health"]["schema_version"],
                restored["health"]["schema_version"],
            ),
        )
        self.assertEqual(counts_before["events"], restored["health"]["counts"]["events"])

    def test_cli_leader_lease_and_escalation_workflow(self) -> None:
        cli_database = self.root / "leader-escalation-cli.sqlite3"
        self._run_cli("init", database=cli_database)
        self._run_cli(
            "task-create",
            "--task-id",
            "cli/supervision",
            "--title",
            "Supervision",
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        self._run_cli(
            "task-join",
            "--task-id",
            "cli/supervision",
            "--agent",
            "agent-beta",
            "--requested-by",
            "agent-alpha",
            database=cli_database,
        )
        completed, lease = self._run_cli(
            "leader-lease-renew",
            "--task-id",
            "cli/supervision",
            "--agent",
            "agent-alpha",
            "--leader-epoch",
            "1",
            "--lease-seconds",
            "30",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("healthy", lease["data"]["state"])
        _, observation = self._run_cli(
            "leader-observation",
            "--task-id",
            "cli/supervision",
            "--agent",
            "agent-beta",
            database=cli_database,
        )
        self.assertEqual("healthy", observation["data"]["state"])

        incident_key = f"event:{uuid4()}"
        completed, opened = self._run_cli(
            "escalation-open",
            "--task-id",
            "cli/supervision",
            "--agent",
            "agent-beta",
            "--leader-epoch",
            "1",
            "--incident-type",
            "response_missing",
            "--incident-key",
            incident_key,
            "--affected-agent",
            "agent-beta",
            "--evidence-pointer",
            "collaboration-design/evidence.md",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(opened["data"]["should_notify"])
        _, replay = self._run_cli(
            "escalation-open",
            "--task-id",
            "cli/supervision",
            "--agent",
            "agent-beta",
            "--leader-epoch",
            "1",
            "--incident-type",
            "response_missing",
            "--incident-key",
            incident_key,
            database=cli_database,
        )
        self.assertFalse(replay["data"]["should_notify"])
        completed, resolved = self._run_cli(
            "escalation-resolve",
            "--escalation-id",
            opened["data"]["escalation_uid"],
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("resolved", resolved["data"]["state"])
        _, listed = self._run_cli(
            "escalations",
            "--task-id",
            "cli/supervision",
            "--agent",
            "agent-beta",
            "--state",
            "resolved",
            database=cli_database,
        )
        self.assertEqual(1, len(listed["data"]["escalations"]))

    def test_cli_work_claim_and_v5_migration(self) -> None:
        cli_database = self.root / "work-claim.sqlite3"
        self._run_cli("init", database=cli_database)
        self._run_cli(
            "task-create",
            "--task-id",
            "cli/work",
            "--title",
            "Work allocation",
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        self._run_cli(
            "task-join",
            "--task-id",
            "cli/work",
            "--agent",
            "agent-beta",
            "--requested-by",
            "agent-alpha",
            database=cli_database,
        )
        package_id = str(uuid4())
        completed, claimed = self._run_cli(
            "work-claim",
            "--task-id",
            "cli/work",
            "--agent",
            "agent-alpha",
            "--worker-agent",
            "agent-beta",
            "--resource",
            "bridge/core",
            "--resource",
            "bridge/tests",
            "--package-id",
            package_id,
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(2, len(claimed["data"]["resources"]))
        _, listed = self._run_cli(
            "work-claims",
            "--task-id",
            "cli/work",
            "--agent",
            "agent-alpha",
            "--state",
            "claimed",
            database=cli_database,
        )
        self.assertEqual(package_id, listed["data"]["claims"][0]["package_uid"])
        completed, finished = self._run_cli(
            "work-claim-finish",
            "--package-id",
            package_id,
            "--agent",
            "agent-beta",
            "--outcome",
            "completed",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("completed", finished["data"]["state"])

        connection = sqlite3.connect(cli_database)
        connection.execute("DROP INDEX idx_work_claim_live_resource")
        connection.execute("DROP INDEX idx_work_claims_task_state")
        connection.execute("DROP INDEX idx_work_claims_package")
        connection.execute("DROP TABLE work_claims")
        connection.execute("UPDATE schema_meta SET value = '5' WHERE key = 'schema_version'")
        connection.commit()
        connection.close()
        migrated = ConversationBridge(cli_database).initialize()
        self.assertEqual(5, migrated["migrated_from"])
        self.assertEqual(7, migrated["schema_version"])

    def test_cli_wake_claim_json_workflow_and_v4_migration(self) -> None:
        v4_database = self.root / "v4.sqlite3"
        v4_bridge = ConversationBridge(v4_database)
        v4_bridge.initialize()
        v4_bridge.create_task("migration/task", "Migration", "agent-alpha")
        v4_bridge.join_task("migration/task", "agent-beta", "agent-alpha")
        event = v4_bridge.publish(
            "migration/task",
            "agent-alpha",
            "request",
            "Keep this event",
            target_agent="agent-beta",
        )
        v4_bridge.acknowledge(event["event_uid"], "agent-beta")
        connection = sqlite3.connect(v4_database)
        connection.execute("DROP INDEX idx_wake_claim_live")
        connection.execute("DROP INDEX idx_wake_claims_event_history")
        connection.execute("DROP TABLE wake_claims")
        connection.execute("UPDATE schema_meta SET value = '4' WHERE key = 'schema_version'")
        connection.commit()
        connection.close()
        migrated = v4_bridge.initialize()
        self.assertEqual(4, migrated["migrated_from"])
        self.assertEqual(7, migrated["schema_version"])
        self.assertEqual(1, v4_bridge.health()["counts"]["events"])
        self.assertEqual(0, v4_bridge.status("migration/task", "agent-beta")["unread"])

        cli_database = self.root / "wake-cli.sqlite3"
        self._run_cli("init", database=cli_database)
        self._run_cli(
            "task-create",
            "--task-id",
            "cli/wake",
            "--title",
            "Wake",
            "--agent",
            "agent-alpha",
            database=cli_database,
        )
        self._run_cli(
            "task-join",
            "--task-id",
            "cli/wake",
            "--agent",
            "agent-beta",
            "--requested-by",
            "agent-alpha",
            database=cli_database,
        )
        _, published = self._run_cli(
            "publish",
            "--task-id",
            "cli/wake",
            "--agent",
            "agent-alpha",
            "--kind",
            "request",
            "--summary",
            "CLI wake",
            "--target-agent",
            "agent-beta",
            database=cli_database,
        )
        completed, claimed = self._run_cli(
            "wake-claim",
            "--task-id",
            "cli/wake",
            "--event",
            published["data"]["event_uid"],
            "--claimer-agent",
            "agent-beta",
            "--adapter-id",
            "agent-beta-headless",
            "--attempt-id",
            str(uuid4()),
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        claim_uid = claimed["data"]["claim_uid"]
        completed, status = self._run_cli(
            "wake-claim-status",
            "--claim-id",
            claim_uid,
            "--agent",
            "agent-beta",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("claimed", status["data"]["state"])
        completed, finished = self._run_cli(
            "wake-claim-finish",
            "--claim-id",
            claim_uid,
            "--claimer-agent",
            "agent-beta",
            "--outcome",
            "dispatched",
            database=cli_database,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("dispatched", finished["data"]["state"])


if __name__ == "__main__":
    unittest.main()
