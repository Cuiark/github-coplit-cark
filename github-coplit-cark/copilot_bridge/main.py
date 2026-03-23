from __future__ import annotations

import argparse
import json

from .mcp_server import BridgeConfig, MCPProtocol, StdioMCPServer
from .state import SessionStore
from .web import start_http_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the GitHub Copilot human-gate MCP bridge.")
    parser.add_argument("--web-host", default="127.0.0.1", help="HTTP host for the human input page.")
    parser.add_argument("--web-port", type=int, default=4317, help="HTTP port for the human input page.")
    parser.add_argument("--public-base-url", default=None, help="Public base URL exposed to MCP clients.")
    parser.add_argument(
        "--transport",
        choices=["http", "stdio", "both"],
        default="http",
        help="MCP transport mode. Defaults to http so the process can be registered as a remote MCP service.",
    )
    parser.add_argument("--db-path", default="bridge.db", help="SQLite database path.")
    parser.add_argument(
        "--sqlite-journal-mode",
        default="PERSIST",
        help="SQLite journal mode. Defaults to PERSIST for better compatibility on restricted filesystems.",
    )
    parser.add_argument(
        "--default-expiry-seconds",
        type=int,
        default=7200,
        help="Default session TTL in seconds.",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="Print recent sessions and their URLs, then exit.",
    )
    parser.add_argument(
        "--list-limit",
        type=int,
        default=20,
        help="How many sessions to print when using --list-sessions.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    public_base_url = args.public_base_url or f"http://{args.web_host}:{args.web_port}"
    config = BridgeConfig(public_base_url=public_base_url)
    store = SessionStore(
        args.db_path,
        default_expiry_seconds=args.default_expiry_seconds,
        journal_mode=args.sqlite_journal_mode,
    )

    if args.list_sessions:
        sessions = store.list_sessions(limit=args.list_limit)
        for session in sessions:
            payload = {
                "session_id": session.session_id,
                "status": session.status,
                "title": session.title,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "ui_url": f"{public_base_url.rstrip('/')}/s/{session.token}",
                "token": session.token,
            }
            print(json.dumps(payload, ensure_ascii=False))
        if not sessions:
            print("No sessions found.")
        return

    protocol = MCPProtocol(store, config)

    if args.transport == "stdio":
        server = StdioMCPServer(protocol)
        server.serve_forever()
        return

    http_server = start_http_server(
        store,
        config,
        protocol,
        args.web_host,
        args.web_port,
        background=args.transport == "both",
    )

    if args.transport == "both":
        server = StdioMCPServer(protocol)
        server.serve_forever()
        return

    http_server.serve_forever()


if __name__ == "__main__":
    main()
