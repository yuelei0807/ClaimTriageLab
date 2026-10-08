"""Minimal SQLite storage for tools, reviews, and immutable audit events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class ToolStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    policy_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS policies (
                    policy_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (claim_id) REFERENCES claims(claim_id)
                );
                CREATE TABLE IF NOT EXISTS review_decisions (
                    review_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES claims(claim_id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    error_code TEXT,
                    duration_ms REAL NOT NULL,
                    attempt_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_integrity (
                    event_id TEXT PRIMARY KEY,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (event_id) REFERENCES audit_events(event_id)
                );
                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS audit_integrity_no_update
                BEFORE UPDATE ON audit_integrity
                BEGIN
                    SELECT RAISE(ABORT, 'audit_integrity is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS audit_integrity_no_delete
                BEFORE DELETE ON audit_integrity
                BEGIN
                    SELECT RAISE(ABORT, 'audit_integrity is immutable');
                END;
                """
            )
            self._backfill_audit_integrity(connection)

    @staticmethod
    def _audit_hash(previous_hash: str, event: dict[str, Any]) -> str:
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{previous_hash}|{payload}".encode()).hexdigest()

    def _backfill_audit_integrity(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        previous_hash = "0" * 64
        for row in rows:
            event = dict(row)
            event_hash = self._audit_hash(previous_hash, event)
            existing = connection.execute(
                "SELECT previous_hash, event_hash FROM audit_integrity WHERE event_id = ?",
                (event["event_id"],),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO audit_integrity VALUES (?, ?, ?)",
                    (event["event_id"], previous_hash, event_hash),
                )
            elif existing["previous_hash"] != previous_hash or existing["event_hash"] != event_hash:
                raise ValueError("audit integrity verification failed")
            previous_hash = event_hash

    def seed_case(
        self,
        claim: dict[str, Any],
        policy: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO claims VALUES (?, ?, ?)",
                (claim["claim_id"], claim["policy_id"], json.dumps(claim, sort_keys=True)),
            )
            connection.execute(
                "INSERT OR REPLACE INTO policies VALUES (?, ?)",
                (policy["policy_id"], json.dumps(policy, sort_keys=True)),
            )
            connection.executemany(
                "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?)",
                [
                    (
                        item["evidence_id"],
                        claim["claim_id"],
                        item["field_name"],
                        json.dumps(item, sort_keys=True),
                    )
                    for item in evidence
                ],
            )

    def get_record(self, table: str, key_column: str, key: str) -> dict[str, Any] | None:
        allowed = {
            ("claims", "claim_id"),
            ("policies", "policy_id"),
            ("evidence", "evidence_id"),
        }
        if (table, key_column) not in allowed:
            raise ValueError("table access is not allowlisted")
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {table} WHERE {key_column} = ?", (key,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def evidence_map(self, claim_id: str, *, max_results: int | None = None) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT field_name, evidence_id FROM evidence
                WHERE claim_id = ? ORDER BY evidence_id""",
                (claim_id,),
            ).fetchall()
        if max_results is not None and len(rows) > max_results:
            raise ValueError(f"evidence retrieval exceeds {max_results} item limit")
        return {row["field_name"]: row["evidence_id"] for row in rows}

    def list_claims(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM claims ORDER BY claim_id"
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def evidence_records(self, claim_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM evidence WHERE claim_id = ? ORDER BY evidence_id",
                (claim_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def reviews_for_case(self, case_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM review_decisions WHERE case_id = ? ORDER BY created_at",
                (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_review_with_audit(
        self,
        *,
        case_id: str,
        reviewer_id: str,
        decision: str,
        reason: str,
        idempotency_key: str,
        correlation_id: str,
        arguments: dict[str, Any],
        deadline_monotonic: float,
        started_monotonic: float,
        attempt_count: int,
    ) -> tuple[dict[str, Any], bool]:
        if time.monotonic() >= deadline_monotonic:
            raise TimeoutError("tool execution deadline expired before review write")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM review_decisions WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                if (
                    existing["case_id"] != case_id
                    or existing["reviewer_id"] != reviewer_id
                    or existing["decision"] != decision
                    or existing["reason"] != reason
                ):
                    raise ValueError("idempotency key was already used for another review payload")
                review = dict(existing)
                replayed = True
            else:
                review = {
                    "review_id": f"review_{uuid4().hex}",
                    "case_id": case_id,
                    "reviewer_id": reviewer_id,
                    "decision": decision,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "created_at": datetime.now(UTC).isoformat(),
                }
                connection.execute(
                    """
                    INSERT INTO review_decisions
                    (review_id, case_id, reviewer_id, decision, reason, idempotency_key, created_at)
                    VALUES (:review_id, :case_id, :reviewer_id, :decision, :reason,
                            :idempotency_key, :created_at)
                    """,
                    review,
                )
                replayed = False
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError("tool execution deadline expired before review commit")
            self._insert_audit(
                connection,
                correlation_id=correlation_id,
                actor_id=reviewer_id,
                tool_name="save_review",
                status="success",
                arguments=arguments,
                error_code=None,
                duration_ms=(time.monotonic() - started_monotonic) * 1_000,
                attempt_count=attempt_count,
            )
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError("tool execution deadline expired before transaction commit")
        return review, replayed

    def _insert_audit(
        self,
        connection: sqlite3.Connection,
        *,
        correlation_id: str,
        actor_id: str,
        tool_name: str,
        status: str,
        arguments: dict[str, Any],
        error_code: str | None,
        duration_ms: float,
        attempt_count: int,
    ) -> None:
        event_id = f"audit_{uuid4().hex}"
        occurred_at = datetime.now(UTC).isoformat()
        arguments_json = json.dumps(arguments, sort_keys=True)
        duration_ms = round(duration_ms, 3)
        connection.execute(
            """
            INSERT INTO audit_events
            (event_id, occurred_at, correlation_id, actor_id, tool_name, status,
             arguments_json, error_code, duration_ms, attempt_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                occurred_at,
                correlation_id,
                actor_id,
                tool_name,
                status,
                arguments_json,
                error_code,
                duration_ms,
                attempt_count,
            ),
        )
        previous = connection.execute(
            """SELECT integrity.event_hash FROM audit_integrity AS integrity
            JOIN audit_events AS event ON event.event_id = integrity.event_id
            ORDER BY event.sequence DESC LIMIT 1"""
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else "0" * 64
        event = dict(
            connection.execute(
                "SELECT * FROM audit_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        )
        connection.execute(
            "INSERT INTO audit_integrity VALUES (?, ?, ?)",
            (event_id, previous_hash, self._audit_hash(previous_hash, event)),
        )

    def audit(
        self,
        *,
        correlation_id: str,
        actor_id: str,
        tool_name: str,
        status: str,
        arguments: dict[str, Any],
        error_code: str | None,
        duration_ms: float,
        attempt_count: int,
    ) -> None:
        with self.connect() as connection:
            self._insert_audit(
                connection,
                correlation_id=correlation_id,
                actor_id=actor_id,
                tool_name=tool_name,
                status=status,
                arguments=arguments,
                error_code=error_code,
                duration_ms=duration_ms,
                attempt_count=attempt_count,
            )

    def audit_events(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        return [dict(row) for row in rows]

    def verify_audit_integrity(self) -> bool:
        with self.connect() as connection:
            self._backfill_audit_integrity(connection)
        return True
