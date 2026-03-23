from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from .prompts import GLOBAL_SYSTEM_PROMPT, tool_control_instruction
from .state import Session, SessionStore, from_iso, utc_now


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class StdioTransport:
    def read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                break
            key, _, value = line.decode("utf-8").partition(":")
            headers[key.strip().lower()] = value.strip()

        length = int(headers.get("content-length", "0"))
        if length <= 0:
            return None
        body = sys.stdin.buffer.read(length)
        return json.loads(body.decode("utf-8"))

    def write_message(self, payload: dict[str, Any]) -> None:
        body = _json_dumps(payload)
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()


@dataclass
class BridgeConfig:
    public_base_url: str
    mcp_http_path: str = "/mcp"
    mcp_sse_path: str = "/sse/"

    @property
    def mcp_http_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}{self.mcp_http_path}"

    @property
    def mcp_sse_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}{self.mcp_sse_path}"

    def message_post_url(self, stream_id: str) -> str:
        return f"{self.public_base_url.rstrip('/')}/messages/?session_id={stream_id}"


class MCPProtocol:
    def __init__(self, store: SessionStore, config: BridgeConfig):
        self.store = store
        self.config = config

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})

        if request_id is None:
            self._handle_notification(method, params)
            return None

        try:
            if method == "initialize":
                result = self._initialize_result()
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self._tool_definitions()}
            elif method == "tools/call":
                result = self._call_tool(params)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown method: {method}"},
                }
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def _handle_notification(self, method: str | None, params: dict[str, Any]) -> None:
        _ = (method, params)
        return

    def _initialize_result(self) -> dict[str, Any]:
        return {
            "protocolVersion": "2025-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "copilot-human-gate-bridge", "version": "0.2.0"},
            "instructions": GLOBAL_SYSTEM_PROMPT,
        }

    def _tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "workflow_wait_for_user",
                "description": (
                    "Create a resumable human-input checkpoint for the current workflow session. "
                    "Use this when the workflow needs a human response before continuing."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "prompt": {"type": "string"},
                        "context_summary": {"type": "string"},
                        "system_instruction": {"type": "string"},
                        "workflow_session_id": {"type": "string"},
                        "step_id": {"type": "string"},
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "label": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": ["text", "textarea", "boolean", "select"],
                                    },
                                    "required": {"type": "boolean"},
                                    "placeholder": {"type": "string"},
                                    "help_text": {"type": "string"},
                                    "default": {},
                                    "options": {
                                        "type": "array",
                                        "items": {
                                            "oneOf": [
                                                {"type": "string"},
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "label": {"type": "string"},
                                                        "value": {"type": "string"},
                                                    },
                                                    "required": ["value"],
                                                    "additionalProperties": False,
                                                },
                                            ]
                                        },
                                    },
                                },
                                "required": ["name", "label", "type"],
                                "additionalProperties": False,
                            },
                        },
                        "client_name": {"type": "string"},
                        "client_session_id": {"type": "string"},
                        "expires_in_seconds": {"type": "integer", "minimum": 60},
                        "metadata": {"type": "object"},
                    },
                    "required": ["title", "prompt"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "workflow_poll",
                "description": (
                    "Poll the current human-input checkpoint. "
                    "Use this after workflow_wait_for_user until input arrives or the session expires."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "workflow_session_id": {"type": "string"},
                        "wait_ms": {"type": "integer", "minimum": 0, "maximum": 10000},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "workflow_wait_until_submitted",
                "description": (
                    "Create a human-input checkpoint and keep this tool call open until the user submits "
                    "the web form or the session expires. Prefer this when the workflow should remain attached "
                    "to the same long-running conversation without relying on repeated polling."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "prompt": {"type": "string"},
                        "context_summary": {"type": "string"},
                        "system_instruction": {"type": "string"},
                        "workflow_session_id": {"type": "string"},
                        "step_id": {"type": "string"},
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "label": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": ["text", "textarea", "boolean", "select"],
                                    },
                                    "required": {"type": "boolean"},
                                    "placeholder": {"type": "string"},
                                    "help_text": {"type": "string"},
                                    "default": {},
                                    "options": {
                                        "type": "array",
                                        "items": {
                                            "oneOf": [
                                                {"type": "string"},
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "label": {"type": "string"},
                                                        "value": {"type": "string"},
                                                    },
                                                    "required": ["value"],
                                                    "additionalProperties": False,
                                                },
                                            ]
                                        },
                                    },
                                },
                                "required": ["name", "label", "type"],
                                "additionalProperties": False,
                            },
                        },
                        "client_name": {"type": "string"},
                        "client_session_id": {"type": "string"},
                        "expires_in_seconds": {"type": "integer", "minimum": 60},
                        "metadata": {"type": "object"},
                        "max_wait_ms": {"type": "integer", "minimum": 0},
                    },
                    "required": ["title", "prompt"],
                    "additionalProperties": False,
                },
            },
        ]

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name == "workflow_wait_for_user":
            payload = self._workflow_wait_for_user(arguments)
        elif name == "workflow_poll":
            payload = self._workflow_poll(arguments)
        elif name == "workflow_wait_until_submitted":
            payload = self._workflow_wait_until_submitted(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")

        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "structuredContent": payload,
            "isError": False,
        }

    def _workflow_wait_for_user(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session, workflow_session_id = self._create_wait_session(arguments)
        return self._session_wait_payload(session, workflow_session_id=workflow_session_id)

    def _workflow_wait_until_submitted(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session, workflow_session_id = self._create_wait_session(arguments)
        max_wait_ms = arguments.get("max_wait_ms")
        if max_wait_ms is None:
            expires_at = self.store.get_session(session.session_id)
            if expires_at is None:
                raise ValueError("Session disappeared after creation.")
            max_wait_ms = max(
                0,
                int((from_iso(expires_at.expires_at) - utc_now()).total_seconds() * 1000),
            )

        payload = self.store.poll_session(session.session_id, wait_ms=int(max_wait_ms))
        payload["ui_url"] = f"{self.config.public_base_url.rstrip('/')}/s/{session.token}"
        payload["session_id"] = session.session_id
        payload["fields"] = session.form_fields
        if workflow_session_id:
            payload["workflow_session_id"] = workflow_session_id
        if session.metadata.get("step_id"):
            payload["step_id"] = session.metadata["step_id"]
        return payload

    def _workflow_poll(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = str(arguments.get("session_id", "")).strip()
        workflow_session_id = str(arguments.get("workflow_session_id", "")).strip()
        wait_ms = int(arguments.get("wait_ms", 0))
        if not session_id and not workflow_session_id:
            raise ValueError("session_id or workflow_session_id is required")

        if session_id:
            payload = self.store.poll_session(session_id, wait_ms=wait_ms)
            if workflow_session_id:
                payload["workflow_session_id"] = workflow_session_id
            else:
                session = self.store.get_session(session_id)
                if session is not None and session.client_session_id:
                    payload["workflow_session_id"] = session.client_session_id
            return payload

        session = self._resolve_workflow_session(workflow_session_id)
        if session is None:
            return {
                "workflow_session_id": workflow_session_id,
                "status": "failed",
                "message": "Unknown workflow session.",
                "system_instruction": tool_control_instruction("failed"),
            }

        payload = self.store.poll_session(session.session_id, wait_ms=wait_ms)
        payload["workflow_session_id"] = workflow_session_id
        return payload

    def _resolve_workflow_session(self, workflow_session_id: str) -> Session | None:
        session = self.store.get_latest_session_by_client_session_id(
            workflow_session_id,
            statuses=["waiting_user"],
        )
        if session is not None:
            return session
        return self.store.get_latest_session_by_client_session_id(workflow_session_id)

    def _session_wait_payload(
        self,
        session: Session,
        workflow_session_id: str | None = None,
    ) -> dict[str, Any]:
        workflow_session_id = workflow_session_id or session.client_session_id
        payload = {
            "session_id": session.session_id,
            "status": "waiting_user",
            "message": "Human input is required before the workflow can continue.",
            "ui_url": f"{self.config.public_base_url.rstrip('/')}/s/{session.token}",
            "fields": session.form_fields,
            "next_action": "poll",
            "poll_after_ms": 3000,
            "system_instruction": session.system_instruction or tool_control_instruction("waiting_user"),
        }
        if workflow_session_id:
            payload["workflow_session_id"] = workflow_session_id
        if session.metadata.get("step_id"):
            payload["step_id"] = session.metadata["step_id"]
        return payload

    def _create_wait_session(self, arguments: dict[str, Any]) -> tuple[Session, str | None]:
        title = str(arguments["title"]).strip()
        prompt = str(arguments["prompt"]).strip()
        context_summary = str(arguments.get("context_summary", "")).strip()
        system_instruction = str(arguments.get("system_instruction", "")).strip()
        fields = arguments.get("fields") or []
        client_name = str(arguments.get("client_name", "")).strip() or None
        client_session_id = str(arguments.get("client_session_id", "")).strip() or None
        workflow_session_id = str(arguments.get("workflow_session_id", "")).strip() or client_session_id
        step_id = str(arguments.get("step_id", "")).strip() or None
        expires_in_seconds = arguments.get("expires_in_seconds")
        metadata = dict(arguments.get("metadata") or {})

        if not title or not prompt:
            raise ValueError("title and prompt are required")
        if fields and not isinstance(fields, list):
            raise ValueError("fields must be an array when provided")

        if workflow_session_id:
            metadata["workflow_session_id"] = workflow_session_id
        if step_id:
            metadata["step_id"] = step_id

        session = self.store.create_wait_session(
            title=title,
            prompt=prompt,
            context_summary=context_summary,
            system_instruction=system_instruction or tool_control_instruction("waiting_user"),
            form_fields=fields,
            client_name=client_name,
            client_session_id=workflow_session_id or client_session_id,
            expires_in_seconds=int(expires_in_seconds) if expires_in_seconds else None,
            metadata=metadata,
        )
        return session, workflow_session_id


class StdioMCPServer:
    def __init__(self, protocol: MCPProtocol):
        self.protocol = protocol
        self.transport = StdioTransport()

    def serve_forever(self) -> None:
        while True:
            message = self.transport.read_message()
            if message is None:
                return
            response = self.protocol.handle_message(message)
            if response is not None:
                self.transport.write_message(response)
