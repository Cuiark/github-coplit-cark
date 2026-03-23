from __future__ import annotations

import html
import json
import queue
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

from .mcp_server import BridgeConfig, MCPProtocol
from .prompts import decorate_submitted_user_input
from .state import SessionStore


def _normalize_options(field: dict[str, Any]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for option in field.get("options") or []:
        if isinstance(option, str):
            options.append({"label": option, "value": option})
        elif isinstance(option, dict):
            value = str(option.get("value", "")).strip()
            if value:
                options.append({"label": str(option.get("label", value)), "value": value})
    return options


def normalize_submission(fields: list[dict[str, Any]], payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not fields:
        user_input = str(payload.get("user_input", "")).strip()
        if not user_input:
            raise ValueError("user_input is required")
        return {"user_input": user_input}, user_input

    normalized: dict[str, Any] = {}
    summary_lines: list[str] = []
    for field in fields:
        name = str(field.get("name", "")).strip()
        label = str(field.get("label", name)).strip() or name
        field_type = str(field.get("type", "text")).strip()
        required = bool(field.get("required", False))
        raw_value = payload.get(name)

        if field_type == "boolean":
            value = bool(raw_value)
            if required and raw_value is None:
                raise ValueError(f"{name} is required")
        else:
            value = "" if raw_value is None else str(raw_value).strip()
            if required and not value:
                raise ValueError(f"{name} is required")
            if field_type == "select" and value:
                allowed_values = {item["value"] for item in _normalize_options(field)}
                if value not in allowed_values:
                    raise ValueError(f"{name} is not a valid option")

        normalized[name] = value
        summary_lines.append(f"{label}: {value}")

    return normalized, "\n".join(summary_lines)


def _normalize_continue_call_next(raw_value: Any) -> bool:
    if raw_value is None:
        return True
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return bool(raw_value)
    return str(raw_value).strip().lower() not in {"", "0", "false", "no", "off"}


def _session_status_copy(status: str) -> tuple[str, str]:
    if status == "submitted":
        return (
            "该会话已提交完成。",
            "这个页面将自动尝试关闭；如果浏览器不允许关闭，会自动返回首页。",
        )
    if status == "expired":
        return (
            "该会话已过期。",
            "当前不再接受输入，页面将自动返回首页。",
        )
    if status != "waiting_user":
        return (
            f"当前会话状态为 {status}。",
            "该页面不再需要继续填写，稍后将自动返回首页。",
        )
    return ("", "")


def _render_form_fields(fields: list[dict[str, Any]]) -> str:
    if not fields:
        return (
            '<textarea name="user_input" '
            'placeholder="请输入当前工作流所需的信息..."></textarea>'
        )

    blocks: list[str] = []
    for index, field in enumerate(fields):
        name = html.escape(str(field.get("name", f"field_{index}")))
        label = html.escape(str(field.get("label", name)))
        field_type = str(field.get("type", "text"))
        placeholder = html.escape(str(field.get("placeholder", "")))
        help_text = html.escape(str(field.get("help_text", "")))
        required_attr = " required" if field.get("required") else ""
        default_value = field.get("default")
        block = [f'<label class="field-label" for="field-{name}">{label}</label>']

        if field_type == "textarea":
            value = html.escape("" if default_value is None else str(default_value))
            block.append(
                f'<textarea id="field-{name}" name="{name}" placeholder="{placeholder}"{required_attr}>{value}</textarea>'
            )
        elif field_type == "boolean":
            checked = " checked" if bool(default_value) else ""
            block.append(
                f'<label class="checkbox"><input id="field-{name}" type="checkbox" name="{name}"{checked}> <span>是</span></label>'
            )
        elif field_type == "select":
            options_html = ['<option value="">请选择</option>']
            for option in _normalize_options(field):
                selected = " selected" if option["value"] == default_value else ""
                options_html.append(
                    f'<option value="{html.escape(option["value"])}"{selected}>{html.escape(option["label"])}</option>'
                )
            block.append(
                f'<select id="field-{name}" name="{name}"{required_attr}>{"".join(options_html)}</select>'
            )
        else:
            value = html.escape("" if default_value is None else str(default_value))
            block.append(
                f'<input id="field-{name}" type="text" name="{name}" value="{value}" placeholder="{placeholder}"{required_attr}>'
            )

        if help_text:
            block.append(f'<div class="help">{help_text}</div>')
        blocks.append(f'<div class="field">{"".join(block)}</div>')
    return "".join(blocks)


def render_home_page(public_base_url: str, waiting_sessions: list[Any]) -> str:
    safe_base_url = html.escape(public_base_url.rstrip("/"))
    latest_url = ""
    if waiting_sessions:
        latest_url = f"{public_base_url.rstrip('/')}/s/{waiting_sessions[0].token}"
    safe_latest_url = html.escape(latest_url)

    session_cards: list[str] = []
    for session in waiting_sessions:
        ui_url = f"{public_base_url.rstrip('/')}/s/{session.token}"
        session_cards.append(
            f"""
            <div class="session-card">
              <div class="session-meta">状态: {html.escape(session.status)} | 更新时间: {html.escape(session.updated_at)}</div>
              <h2>{html.escape(session.title)}</h2>
              <div class="session-prompt">{html.escape(session.prompt)}</div>
              <div class="url-label">可用填写链接</div>
              <a class="url-link" href="{html.escape(ui_url)}" target="_blank" rel="noreferrer">{html.escape(ui_url)}</a>
            </div>
            """
        )

    if not session_cards:
        session_cards.append(
            """
            <div class="empty-state">
              <div class="url-label">可用填写链接</div>
              <div class="empty-copy">当前没有待填写的会话。</div>
            </div>
            """
        )

    latest_block = (
        f'<a class="hero-link" href="{safe_latest_url}" target="_blank" rel="noreferrer">{safe_latest_url}</a>'
        if safe_latest_url
        else '<div class="hero-empty">当前还没有可用链接，请先创建一个等待人工输入的会话。</div>'
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="5">
  <title>人工输入桥接面板</title>
  <style>
    :root {{
      color-scheme: light;
      --bg-1: #f4efe6;
      --bg-2: #efe0cd;
      --panel: rgba(255, 252, 247, 0.9);
      --text: #1f1a14;
      --muted: #6f6252;
      --accent: #0b6e4f;
      --accent-2: #17494d;
      --border: rgba(59, 38, 18, 0.12);
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, rgba(255, 251, 245, 0.95), transparent 28%),
        linear-gradient(135deg, var(--bg-1), var(--bg-2));
      min-height: 100vh;
    }}
    .wrap {{
      max-width: 1040px;
      margin: 0 auto;
      padding: 40px 24px 56px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255,255,255,0.78), rgba(247,238,228,0.92));
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 24px 60px rgba(40, 25, 10, 0.08);
      margin-bottom: 24px;
    }}
    .eyebrow {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 42px;
      line-height: 1.05;
    }}
    .hero-copy {{
      color: var(--muted);
      line-height: 1.6;
      margin-bottom: 16px;
      max-width: 760px;
    }}
    .hero-label, .url-label {{
      color: var(--accent-2);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 12px;
      margin-bottom: 8px;
    }}
    .hero-link, .url-link {{
      display: inline-block;
      text-decoration: none;
      color: white;
      background: linear-gradient(135deg, var(--accent-2), var(--accent));
      border-radius: 999px;
      padding: 12px 18px;
      word-break: break-all;
      line-height: 1.4;
    }}
    .hero-empty, .empty-copy {{
      color: var(--muted);
      line-height: 1.5;
    }}
    .meta-row {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    }}
    .session-card, .empty-state {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 20px;
      box-shadow: 0 18px 42px rgba(40, 25, 10, 0.06);
    }}
    .session-meta {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 10px;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 24px;
      line-height: 1.2;
    }}
    .session-prompt {{
      white-space: pre-wrap;
      line-height: 1.55;
      margin-bottom: 14px;
    }}
    @media (max-width: 640px) {{
      .wrap {{
        padding: 24px 16px 40px;
      }}
      h1 {{
        font-size: 34px;
      }}
      .hero, .session-card, .empty-state {{
        padding: 20px;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="eyebrow">人工输入桥接</div>
      <h1>可用链接面板</h1>
      <div class="hero-copy">打开 <strong>{safe_base_url}/</strong> 即可查看最新的可用填写链接。页面会每 5 秒自动刷新，并显示当前仍在等待人工输入的会话。</div>
      <div class="hero-label">最新可用链接</div>
      {latest_block}
      <div class="meta-row">待填写会话数量: {len(waiting_sessions)}</div>
    </div>
    <div class="grid">
      {''.join(session_cards)}
    </div>
  </div>
</body>
</html>
"""


def render_session_page(
    title: str,
    prompt: str,
    context_summary: str,
    token: str,
    status: str,
    fields: list[dict[str, Any]],
) -> str:
    safe_title = html.escape(title)
    safe_prompt = html.escape(prompt)
    safe_context = html.escape(context_summary)
    safe_token = html.escape(token)
    safe_fields_json = html.escape(json.dumps(fields, ensure_ascii=False))
    is_waiting = status == "waiting_user"
    status_title, status_message = _session_status_copy(status)
    safe_status_title = html.escape(status_title)
    safe_status_message = html.escape(status_message)
    form_html = (
        f"""
      <form id="reply-form" data-fields="{safe_fields_json}">
        {_render_form_fields(fields)}
        <div class="option-card">
          <label class="checkbox" for="continue-call-next">
            <input id="continue-call-next" type="checkbox" name="continue_call_next" checked>
            <span>下次是否接着调用</span>
          </label>
          <div class="help">默认勾选。勾选后，系统会在提交给 LLM 的回答前后自动加入继续调用 copilot_human_gate_bridge 的提示。</div>
        </div>
        <input type="hidden" name="token" value="{safe_token}">
        <button id="submit-button" type="submit">提交</button>
      </form>
      <div id="ok" class="ok">提交成功，页面将自动尝试关闭；若关闭失败，会自动返回首页。</div>
        """
        if is_waiting
        else f"""
      <div class="notice">
        <div class="notice-title">{safe_status_title}</div>
        <div>{safe_status_message}</div>
      </div>
      <a class="home-link" href="/">返回首页</a>
        """
    )
    script = (
        """
  <script>
    const form = document.getElementById('reply-form');
    const ok = document.getElementById('ok');
    const submitButton = document.getElementById('submit-button');
    const fields = JSON.parse(form?.dataset.fields || '[]');
    const continueCallInput = document.getElementById('continue-call-next');

    function closeOrRedirectHome() {
      window.close();
      window.setTimeout(() => {
        window.location.replace('/');
      }, 300);
    }

    function collectPayload() {
      const payload = {
        token: form.querySelector('input[name="token"]').value,
        continue_call_next: Boolean(continueCallInput?.checked ?? true)
      };
      if (!fields.length) {
        payload.user_input = form.querySelector('[name="user_input"]').value;
        return payload;
      }
      const submitted = {};
      for (const field of fields) {
        const element = form.querySelector(`[name="${field.name}"]`);
        if (!element) continue;
        if (field.type === 'boolean') {
          submitted[field.name] = Boolean(element.checked);
        } else {
          submitted[field.name] = element.value;
        }
      }
      payload.fields = submitted;
      return payload;
    }

    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = '提交中...';
      }

      try {
        const payload = collectPayload();
        const response = await fetch('/api/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (response.ok) {
          ok.style.display = 'block';
          form.style.display = 'none';
          window.setTimeout(closeOrRedirectHome, 1200);
          return;
        }

        const errorPayload = await response.json().catch(() => null);
        const message = errorPayload?.error || '提交失败。';
        alert(message);
      } finally {
        if (submitButton && form?.style.display !== 'none') {
          submitButton.disabled = false;
          submitButton.textContent = '提交';
        }
      }
    });
  </script>
        """
        if is_waiting
        else """
  <script>
    function closeOrRedirectHome() {
      window.close();
      window.setTimeout(() => {
        window.location.replace('/');
      }, 300);
    }

    window.setTimeout(closeOrRedirectHome, 1500);
  </script>
        """
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f0e8;
      --panel: #fffdf8;
      --text: #1f1b17;
      --muted: #6b6258;
      --accent: #0d5c63;
      --border: #d8cbbb;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: radial-gradient(circle at top left, #fff7ef 0%, var(--bg) 55%, #efe1d3 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 760px;
      margin: 48px auto;
      padding: 24px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 24px;
      box-shadow: 0 20px 50px rgba(55, 39, 22, 0.08);
    }}
    .eyebrow {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 12px;
      margin-bottom: 8px;
    }}
    h1 {{
      margin: 0 0 16px;
      font-size: 34px;
      line-height: 1.1;
    }}
    .prompt, .context {{
      white-space: pre-wrap;
      line-height: 1.55;
      margin-bottom: 16px;
    }}
    textarea, input, select {{
      width: 100%;
      padding: 14px;
      border-radius: 14px;
      border: 1px solid var(--border);
      font: inherit;
      box-sizing: border-box;
      background: #fff;
    }}
    textarea {{
      min-height: 180px;
      resize: vertical;
    }}
    .field {{
      margin-bottom: 18px;
    }}
    .field-label {{
      display: block;
      margin-bottom: 8px;
      font-weight: 600;
    }}
    .help {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.4;
    }}
    .checkbox {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .checkbox span {{
      line-height: 1.4;
    }}
    .checkbox input {{
      width: auto;
    }}
    .option-card {{
      margin-top: 20px;
      padding: 14px 16px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: #fbf6f0;
    }}
    button {{
      margin-top: 16px;
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      padding: 12px 18px;
      font: inherit;
      cursor: pointer;
    }}
    .status {{
      margin-bottom: 16px;
      color: var(--muted);
    }}
    .ok {{
      margin-top: 16px;
      color: var(--accent);
      display: none;
    }}
    .notice {{
      margin-top: 20px;
      padding: 16px 18px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: #fbf6f0;
      line-height: 1.6;
    }}
    .notice-title {{
      font-weight: 600;
      margin-bottom: 6px;
    }}
    .home-link {{
      display: inline-block;
      margin-top: 18px;
      text-decoration: none;
      color: white;
      background: var(--accent);
      border-radius: 999px;
      padding: 12px 18px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <div class="eyebrow">需要人工输入</div>
      <div class="status">当前状态: {html.escape(status)}</div>
      <h1>{safe_title}</h1>
      <div class="prompt">{safe_prompt}</div>
      <div class="context">{safe_context}</div>
      {form_html}
    </div>
  </div>
  {script}
</body>
</html>
"""


class SSEStreamRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._queues: dict[str, queue.Queue[dict[str, Any]]] = {}

    def open(self) -> tuple[str, queue.Queue[dict[str, Any]]]:
        stream_id = uuid.uuid4().hex
        stream_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._queues[stream_id] = stream_queue
        return stream_id, stream_queue

    def close(self, stream_id: str) -> None:
        with self._lock:
            self._queues.pop(stream_id, None)

    def publish(self, stream_id: str, payload: dict[str, Any]) -> bool:
        with self._lock:
            stream_queue = self._queues.get(stream_id)
        if stream_queue is None:
            return False
        stream_queue.put(payload)
        return True


class BridgeHTTPRequestHandler(BaseHTTPRequestHandler):
    store: SessionStore
    config: BridgeConfig
    protocol: MCPProtocol
    sse_registry: SSEStreamRegistry

    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_empty(self, status: int = HTTPStatus.ACCEPTED) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def _send_html(self, body: str, status: int = HTTPStatus.OK) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            waiting_sessions = self.store.list_sessions(limit=100, status="waiting_user")
            self._send_json(
                {
                    "ok": True,
                    "public_base_url": self.config.public_base_url,
                    "mcp_http_url": self.config.mcp_http_url,
                    "mcp_sse_url": self.config.mcp_sse_url,
                    "active_waiting_sessions": len(waiting_sessions),
                }
            )
            return
        if parsed.path == "/":
            waiting_sessions = self.store.list_sessions(limit=20, status="waiting_user")
            body = render_home_page(self.config.public_base_url, waiting_sessions)
            self._send_html(body)
            return
        if parsed.path in {self.config.mcp_sse_path.rstrip("/"), self.config.mcp_sse_path}:
            self._handle_sse_stream()
            return
        if parsed.path.startswith("/s/"):
            token = parsed.path.split("/", 2)[2]
            session = self.store.get_session_by_token(token)
            if session is None:
                self._send_html("<h1>未找到会话</h1>", status=HTTPStatus.NOT_FOUND)
                return
            body = render_session_page(
                title=session.title,
                prompt=session.prompt,
                context_summary=session.context_summary,
                token=session.token,
                status=session.status,
                fields=session.form_fields,
            )
            self._send_html(body)
            return
        self._send_html("<h1>页面不存在</h1>", status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/submit":
            self._handle_submit()
            return
        if parsed.path == self.config.mcp_http_path:
            self._handle_http_mcp()
            return
        if parsed.path in {"/messages", "/messages/"}:
            self._handle_sse_message(parsed)
            return
        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_submit(self) -> None:
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, status=HTTPStatus.BAD_REQUEST)
            return
        token = str(payload.get("token", "")).strip()
        if not token:
            self._send_json({"error": "token is required"}, status=HTTPStatus.BAD_REQUEST)
            return
        session = self.store.get_session_by_token(token)
        if session is None:
            self._send_json({"error": "Session not found or not waiting"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            submitted_data, user_input = normalize_submission(session.form_fields, payload.get("fields") or payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        continue_call_next = _normalize_continue_call_next(payload.get("continue_call_next"))
        decorated_user_input = decorate_submitted_user_input(user_input, continue_call_next)
        session = self.store.submit_user_input(token, decorated_user_input, submission=submitted_data)
        if session is None:
            self._send_json({"error": "Session not found or not waiting"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(
            {
                "ok": True,
                "session_id": session.session_id,
                "status": session.status,
                "continue_call_next": continue_call_next,
            }
        )

    def _handle_http_mcp(self) -> None:
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        response = self.protocol.handle_message(payload)
        if response is None:
            self._send_empty()
            return
        self._send_json(response)

    def _handle_sse_stream(self) -> None:
        stream_id, stream_queue = self.sse_registry.open()
        endpoint = self.config.message_post_url(stream_id)
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self._write_sse("endpoint", endpoint)

            while True:
                try:
                    payload = stream_queue.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self._write_sse("message", json.dumps(payload, ensure_ascii=False))
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.sse_registry.close(stream_id)

    def _write_sse(self, event: str, data: str) -> None:
        lines = [f"event: {event}\n"]
        for line in data.splitlines() or [""]:
            lines.append(f"data: {line}\n")
        lines.append("\n")
        self.wfile.write("".join(lines).encode("utf-8"))
        self.wfile.flush()

    def _handle_sse_message(self, parsed: Any) -> None:
        stream_id = parse_qs(parsed.query).get("session_id", [""])[0].strip()
        if not stream_id:
            self._send_json({"error": "session_id is required"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, status=HTTPStatus.BAD_REQUEST)
            return

        response = self.protocol.handle_message(payload)
        if response is not None and not self.sse_registry.publish(stream_id, response):
            self._send_json({"error": "Unknown SSE session"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_empty()

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_http_server(
    store: SessionStore,
    config: BridgeConfig,
    protocol: MCPProtocol,
    host: str,
    port: int,
    background: bool = False,
) -> ThreadingHTTPServer:
    sse_registry = SSEStreamRegistry()
    handler = type(
        "ConfiguredBridgeHandler",
        (BridgeHTTPRequestHandler,),
        {
            "store": store,
            "config": config,
            "protocol": protocol,
            "sse_registry": sse_registry,
        },
    )
    server = ThreadingHTTPServer((host, port), handler)
    if background:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
    return server


def start_web_server(
    store: SessionStore,
    host: str,
    port: int,
    public_base_url: str,
) -> ThreadingHTTPServer:
    config = BridgeConfig(public_base_url=public_base_url)
    protocol = MCPProtocol(store, config)
    return start_http_server(store, config, protocol, host, port, background=True)
