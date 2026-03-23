# Implementation Plan

## Goal

Build a cross-client MCP bridge that lets an LLM pause for human input through a standalone web page, then continue the same workflow without relying on each client's built-in chat UI.

Primary product target:

- GitHub Copilot

Compatibility targets:

- VS Code
- Codex CLI
- Claude Code CLI
- OpenCode

## Phase 1: Protocol and Persistence

Status: in progress

Deliverables:

- MCP server over stdio
- External session store
- Human-input web page
- Two core tools:
  - `workflow_wait_for_user`
  - `workflow_poll`
- Global system prompt and tool-return control instruction

Notes:

- The bridge must not depend on client-specific elicitation support.
- The bridge maintains its own persistence instead of reusing opaque client conversation stores.
- Client identifiers can be stored for correlation, but not as the source of truth.

## Phase 2: Upstream Workflow Runner

Status: pending

Deliverables:

- A workflow runner that calls the upstream model
- Configurable model backend
- Multi-step task loop:
  - think
  - call tools
  - wait for human input
  - resume

Notes:

- The current target backend is GitHub Copilot using Claude Opus, but the bridge should keep the runner abstract enough to swap providers later.

## Phase 3: Cross-Client Integration

Status: pending

Deliverables:

- Client-specific MCP registration examples
- Tool descriptions tuned for each client
- Validation matrix across:
  - VS Code
  - Codex CLI
  - Claude Code CLI
  - OpenCode

Notes:

- "Single billed user prompt" is mainly a GitHub Copilot concern.
- Other clients may have different request and token accounting rules.

## Phase 4: Production Hardening

Status: pending

Deliverables:

- Authentication and signed URLs
- Session cleanup jobs
- Audit logs
- Reverse proxy deployment support
- Rich form definitions
- Structured validation of user input

## Hard Constraints

### Long waits

The desired wait window is 2 hours or more. The external session store can support this.

What cannot be guaranteed across all clients:

- One transport request staying open for 2 hours
- One uninterrupted agent loop with no timeout
- One client preserving active polling forever

The design should therefore support both:

- short poll loops for best-effort same-turn continuation
- resumable sessions after client timeout or interruption

### Session persistence

The bridge cannot literally reuse the internal persistence implementation of VS Code, Codex CLI, Claude Code CLI, or OpenCode.

Instead, the bridge should:

- persist its own workflow state
- optionally tag records with client identifiers
- resume from the bridge state no matter which client reconnects later

## Immediate Next Changes

1. Add a runner abstraction for the upstream model call.
2. Extend the web UI from free text to dynamic field definitions.
3. Add an example MCP client configuration for GitHub Copilot in VS Code.
4. Add tool-call transcript examples showing the expected loop.
