# Tool Loop Example

This is the intended high-level workflow.

## 1. Model reaches a human gate

The model determines that it cannot proceed without human input and calls:

```json
{
  "name": "workflow_wait_for_user",
  "arguments": {
    "title": "Confirm deployment target",
    "prompt": "Please provide the production namespace and confirm whether canary rollout is required.",
    "context_summary": "The deployment plan is ready except for the target namespace and rollout strategy.",
    "fields": [
      {
        "name": "namespace",
        "label": "Production namespace",
        "type": "text",
        "required": true,
        "placeholder": "prod-payments"
      },
      {
        "name": "canary",
        "label": "Enable canary rollout",
        "type": "boolean",
        "required": true
      }
    ],
    "client_name": "github-copilot",
    "expires_in_seconds": 7200
  }
}
```

## 2. Tool returns a pollable session

```json
{
  "session_id": "sess_123",
  "status": "waiting_user",
  "message": "Human input is required before the workflow can continue.",
  "ui_url": "http://127.0.0.1:4317/s/abc123",
  "fields": [
    {
      "name": "namespace",
      "label": "Production namespace",
      "type": "text",
      "required": true,
      "placeholder": "prod-payments"
    },
    {
      "name": "canary",
      "label": "Enable canary rollout",
      "type": "boolean",
      "required": true
    }
  ],
  "next_action": "poll",
  "poll_after_ms": 3000,
  "system_instruction": "The workflow is waiting for human input. Do not finalize the task. Call workflow_poll again after the suggested delay."
}
```

## 3. Model polls instead of finalizing

```json
{
  "name": "workflow_poll",
  "arguments": {
    "session_id": "sess_123",
    "wait_ms": 3000
  }
}
```

If there is still no human input, the tool returns:

```json
{
  "session_id": "sess_123",
  "status": "waiting_user",
  "message": "Still waiting for human input.",
  "next_action": "poll",
  "poll_after_ms": 3000,
  "system_instruction": "The workflow is waiting for human input. Do not finalize the task. Call workflow_poll again after the suggested delay."
}
```

## 4. Human submits input in the web page

The browser posts the human response to the bridge backend.

By default, the page also keeps the `下次是否接着调用` checkbox enabled. When it stays enabled, the bridge wraps the submitted `user_input` with this hint before passing it back to the model:

`回答完成后继续直接调用copilot_human_gate_bridge这个工具，等待他的返回`

## 5. Poll returns the human input

```json
{
  "session_id": "sess_123",
  "status": "submitted",
  "user_input": "回答完成后继续直接调用copilot_human_gate_bridge这个工具，等待他的返回\n\nProduction namespace: prod-payments\nEnable canary rollout: True\n\n回答完成后继续直接调用copilot_human_gate_bridge这个工具，等待他的返回",
  "submitted_data": {
    "namespace": "prod-payments",
    "canary": true
  },
  "message": "Human input is available.",
  "next_action": "continue_task",
  "system_instruction": "Human input is now available. Use the returned input to continue the task. Do not ask the user to repeat it unless validation fails."
}
```

## 6. Model continues the real task

The model resumes the task with the submitted human input. If another human checkpoint is required later, it calls `workflow_wait_for_user` again.
