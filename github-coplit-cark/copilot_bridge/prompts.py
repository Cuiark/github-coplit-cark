GLOBAL_SYSTEM_PROMPT = """\
You are participating in a workflow controlled by external MCP tools.

Rules:
1. If you need missing information, approval, confirmation, or a human-provided value, prefer calling `workflow_wait_until_submitted`.
2. Use `workflow_wait_for_user` plus `workflow_poll` only when you intentionally need a non-blocking checkpoint.
3. After calling a waiting workflow tool, do not provide a final answer.
4. If a workflow tool returns `status=waiting_user` or `status=running`, call `workflow_poll` instead of finalizing unless the blocking tool is already holding the workflow open.
5. If a workflow tool returns a `system_instruction` field, treat it as authoritative control for the current workflow step.
6. Prefer maintaining the same long-running workflow session instead of ending the task early. If follow-up human steering may still be needed, create another wait checkpoint rather than finalizing.
7. When available, keep using the same `workflow_session_id` across related wait and poll calls for the same user workflow.
8. Only provide a final answer when the workflow is actually complete and no further human checkpoint is required.
9. If the tool returns `status=submitted`, incorporate the provided human input and continue the task. If you need more human input later, call another waiting workflow tool again.
10. If the tool returns `status=expired` or `status=failed`, explain the issue briefly and stop the workflow unless recovery is possible.
"""

CONTINUE_BRIDGE_CALL_PROMPT = "回答完成后继续直接调用copilot_human_gate_bridge这个工具，等待他的返回"


def decorate_submitted_user_input(user_input: str, continue_call_next: bool) -> str:
    normalized = str(user_input or "").strip()
    if not normalized or not continue_call_next:
        return normalized
    return f"{CONTINUE_BRIDGE_CALL_PROMPT}\n\n{normalized}\n\n{CONTINUE_BRIDGE_CALL_PROMPT}"


def tool_control_instruction(status: str) -> str:
    if status == "waiting_user":
        return (
            "The workflow is waiting for human input. "
            "Do not finalize the task. Call workflow_poll again after the suggested delay."
        )
    if status == "submitted":
        return (
            "Human input is now available. Use the returned input to continue the task. "
            "Do not ask the user to repeat it unless validation fails."
        )
    if status == "expired":
        return (
            "The waiting session expired before human input arrived. "
            "Do not pretend the input exists. Report the expiration or create a new wait session."
        )
    return (
        "Follow the workflow state exactly. Do not provide a final answer until the state explicitly allows it."
    )
