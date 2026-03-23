from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .prompts import tool_control_instruction


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class Session:
    session_id: str
    token: str
    status: str
    client_name: str | None
    client_session_id: str | None
    title: str
    prompt: str
    context_summary: str
    system_instruction: str
    form_fields_json: str
    user_input: str | None
    submission_json: str
    created_at: str
    updated_at: str
    expires_at: str
    metadata_json: str

    @property
    def metadata(self) -> dict[str, Any]:
        if not self.metadata_json:
            return {}
        return json.loads(self.metadata_json)

    @property
    def form_fields(self) -> list[dict[str, Any]]:
        if not self.form_fields_json:
            return []
        return json.loads(self.form_fields_json)

    @property
    def submission(self) -> dict[str, Any]:
        if not self.submission_json:
            return {}
        return json.loads(self.submission_json)


class SessionStore:
    def __init__(
        self,
        db_path: str | Path,
        default_expiry_seconds: int = 7200,
        journal_mode: str = "PERSIST",
    ):
        self.db_path = str(db_path)
        self.default_expiry_seconds = default_expiry_seconds
        self.journal_mode = journal_mode
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._configure_connection()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return self._conn

    def _configure_connection(self) -> None:
        conn = self._connect()
        conn.execute("PRAGMA busy_timeout = 5000")

        candidates: list[str] = []
        for mode in [self.journal_mode, "PERSIST", "TRUNCATE", "MEMORY", "OFF"]:
            normalized = str(mode or "").strip().upper()
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        last_error: sqlite3.OperationalError | None = None
        for mode in candidates:
            try:
                row = conn.execute(f"PRAGMA journal_mode={mode}").fetchone()
                if row and str(row[0]).strip():
                    self.journal_mode = str(row[0]).strip().upper()
                    return
            except sqlite3.OperationalError as exc:
                last_error = exc

        if last_error is not None:
            tried = ", ".join(candidates)
            raise sqlite3.OperationalError(
                f"Unable to configure SQLite journal mode for {self.db_path}. "
                f"Tried: {tried}. Last error: {last_error}"
            ) from last_error

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    client_name TEXT,
                    client_session_id TEXT,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    context_summary TEXT NOT NULL,
                    system_instruction TEXT NOT NULL,
                    form_fields_json TEXT NOT NULL DEFAULT '[]',
                    user_input TEXT,
                    submission_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "sessions", "form_fields_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "sessions", "submission_json", "TEXT NOT NULL DEFAULT '{}'")
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def create_wait_session(
        self,
        *,
        title: str,
        prompt: str,
        context_summary: str = "",
        system_instruction: str = "",
        form_fields: list[dict[str, Any]] | None = None,
        client_name: str | None = None,
        client_session_id: str | None = None,
        expires_in_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        now = utc_now()
        expiry = now + timedelta(seconds=expires_in_seconds or self.default_expiry_seconds)
        session_id = f"sess_{uuid.uuid4().hex}"
        token = uuid.uuid4().hex
        session = Session(
            session_id=session_id,
            token=token,
            status="waiting_user",
            client_name=client_name,
            client_session_id=client_session_id,
            title=title,
            prompt=prompt,
            context_summary=context_summary,
            system_instruction=system_instruction or tool_control_instruction("waiting_user"),
            form_fields_json=json.dumps(form_fields or [], ensure_ascii=True),
            user_input=None,
            submission_json="{}",
            created_at=to_iso(now),
            updated_at=to_iso(now),
            expires_at=to_iso(expiry),
            metadata_json=json.dumps(metadata or {}, ensure_ascii=True),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, token, status, client_name, client_session_id,
                    title, prompt, context_summary, system_instruction, form_fields_json, user_input,
                    submission_json,
                    created_at, updated_at, expires_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.token,
                    session.status,
                    session.client_name,
                    session.client_session_id,
                    session.title,
                    session.prompt,
                    session.context_summary,
                    session.system_instruction,
                    session.form_fields_json,
                    session.user_input,
                    session.submission_json,
                    session.created_at,
                    session.updated_at,
                    session.expires_at,
                    session.metadata_json,
                ),
            )
            conn.commit()
        return session

    def get_session(self, session_id: str) -> Session | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_session(row)

    def get_session_by_token(self, token: str) -> Session | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
        return self._row_to_session(row)

    def list_sessions(
        self,
        limit: int = 20,
        status: str | None = None,
        client_session_id: str | None = None,
    ) -> list[Session]:
        query = "SELECT * FROM sessions"
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if client_session_id:
            clauses.append("client_session_id = ?")
            params.append(client_session_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(int(limit), 1))

        with self._lock, self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [session for row in rows if (session := self._row_to_session(row)) is not None]

    def get_latest_session_by_client_session_id(
        self,
        client_session_id: str,
        statuses: list[str] | None = None,
    ) -> Session | None:
        if not client_session_id:
            return None

        query = "SELECT * FROM sessions WHERE client_session_id = ?"
        params: list[Any] = [client_session_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY created_at DESC LIMIT 1"

        with self._lock, self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return self._row_to_session(row)

    def submit_user_input(
        self,
        token: str,
        user_input: str,
        submission: dict[str, Any] | None = None,
    ) -> Session | None:
        now = to_iso(utc_now())
        submission_json = json.dumps(submission or {}, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, user_input = ?, submission_json = ?, updated_at = ?
                WHERE token = ? AND status = 'waiting_user'
                """,
                ("submitted", user_input, submission_json, now, token),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
        return self._row_to_session(row)

    def poll_session(self, session_id: str, wait_ms: int = 0) -> dict[str, Any]:
        deadline = time.time() + max(wait_ms, 0) / 1000.0
        while True:
            session = self.get_session(session_id)
            if session is None:
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": "Unknown session.",
                    "system_instruction": tool_control_instruction("failed"),
                }

            now = utc_now()
            if from_iso(session.expires_at) <= now and session.status == "waiting_user":
                self._mark_expired(session.session_id)
                session = self.get_session(session.session_id)
                if session is None:
                    return {
                        "session_id": session_id,
                        "status": "failed",
                        "message": "Session disappeared after expiration update.",
                        "system_instruction": tool_control_instruction("failed"),
                    }

            if session.status != "waiting_user":
                return self._poll_payload(session)

            if time.time() >= deadline:
                return self._poll_payload(session)
            time.sleep(0.25)

    def _mark_expired(self, session_id: str) -> None:
        now = to_iso(utc_now())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, updated_at = ?
                WHERE session_id = ? AND status = 'waiting_user'
                """,
                ("expired", now, session_id),
            )
            conn.commit()

    def _poll_payload(self, session: Session) -> dict[str, Any]:
        if session.status == "submitted":
            return {
                "session_id": session.session_id,
                "status": "submitted",
                "user_input": session.user_input or "",
                "message": "Human input is available.",
                "submitted_data": session.submission,
                "system_instruction": tool_control_instruction("submitted"),
                "next_action": "continue_task",
            }
        if session.status == "expired":
            return {
                "session_id": session.session_id,
                "status": "expired",
                "message": "The waiting session expired before any human input was submitted.",
                "system_instruction": tool_control_instruction("expired"),
                "next_action": "abort_or_restart",
            }
        return {
            "session_id": session.session_id,
            "status": "waiting_user",
            "message": "Still waiting for human input.",
            "fields": session.form_fields,
            "system_instruction": session.system_instruction or tool_control_instruction("waiting_user"),
            "next_action": "poll",
            "poll_after_ms": 3000,
        }

    def _row_to_session(self, row: sqlite3.Row | None) -> Session | None:
        if row is None:
            return None
        return Session(
            session_id=row["session_id"],
            token=row["token"],
            status=row["status"],
            client_name=row["client_name"],
            client_session_id=row["client_session_id"],
            title=row["title"],
            prompt=row["prompt"],
            context_summary=row["context_summary"],
            system_instruction=row["system_instruction"],
            form_fields_json=row["form_fields_json"],
            user_input=row["user_input"],
            submission_json=row["submission_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            metadata_json=row["metadata_json"],
        )
