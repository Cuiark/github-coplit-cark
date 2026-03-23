# Codex CLI 与 OpenCode 接入示例

## 1. 目的

本文档说明如何把当前项目提供的 MCP 工具接入：

- `Codex CLI`
- `OpenCode`

目标是让这两个客户端都能调用本项目提供的两个工具：

- `workflow_wait_for_user`
- `workflow_poll`

并通过外部网页完成人工输入。

## 2. 前提

在接入客户端之前，先确保本项目的 MCP 服务可以正常启动。

在项目根目录执行：

```bash
python -m copilot_bridge.main --web-host 127.0.0.1 --web-port 4317 --db-path bridge.db
```

如果你的网页入口不是本机地址，而是通过反向代理对外提供，请改成：

```bash
python -m copilot_bridge.main --web-host 0.0.0.0 --web-port 4317 --public-base-url https://your-host.example.com --db-path bridge.db
```

## 3. Codex CLI 接入

### 3.1 官方配置方式

根据 OpenAI 官方文档，`Codex` 可以通过两种方式配置 MCP：

- 使用 `codex mcp add ...`
- 直接编辑 `~/.codex/config.toml`

官方公开示例明确给出了：

- `codex mcp add <name> --url <remote-mcp-url>`
- `~/.codex/config.toml` 中的 `[mcp_servers.<name>]` 配置块

官方示例主要展示的是远程 HTTP MCP。  
下面给出的本项目配置，是**基于 Codex 官方的 `config.toml` 结构推断出的本地 stdio 形式适配写法**。实际字段名如果你的本地 Codex 版本不同，可能需要按客户端实际报错微调。

### 3.2 推荐做法

如果你的 Codex CLI 版本支持直接通过命令添加本地 MCP，优先使用命令。  
如果没有这个能力，直接编辑配置文件。

### 3.3 `~/.codex/config.toml` 示例

可以在 `~/.codex/config.toml` 中加入一段：

```toml
[mcp_servers.copilot_human_gate_bridge]
command = "python"
args = ["-m", "copilot_bridge.main", "--web-host", "127.0.0.1", "--web-port", "4317", "--db-path", "bridge.db"]
```

如果网页需要通过外部地址访问：

```toml
[mcp_servers.copilot_human_gate_bridge]
command = "python"
args = [
  "-m",
  "copilot_bridge.main",
  "--web-host",
  "0.0.0.0",
  "--web-port",
  "4317",
  "--public-base-url",
  "https://your-host.example.com",
  "--db-path",
  "bridge.db"
]
```

### 3.4 使用方式

接入成功后，建议在 prompt 或规则文件里明确告诉 Codex：

```text
当任务缺少人工输入、审批或确认时，调用 workflow_wait_for_user。
当工具返回 waiting_user 时，不要直接结束回答，继续调用 workflow_poll。
当工具返回 submitted 时，使用 submitted_data 继续任务。
```

你也可以在项目规则文件中加入类似约束，使 Codex 更稳定地调用工具。

### 3.5 一个最小使用示例

你可以对 Codex 提一个类似请求：

```text
如果缺少部署参数，不要猜测。
请使用 copilot_human_gate_bridge 提供的工具等待我填写参数，再继续完成部署方案。
```

当 Codex 判断缺少信息时，它应调用：

```json
{
  "name": "workflow_wait_for_user",
  "arguments": {
    "title": "确认部署参数",
    "prompt": "请补充生产环境命名空间。",
    "fields": [
      {
        "name": "namespace",
        "label": "生产命名空间",
        "type": "text",
        "required": true
      }
    ],
    "client_name": "codex-cli"
  }
}
```

随后它会拿到 `ui_url`，用户打开网页填写，之后再通过 `workflow_poll` 获取结果。

## 4. OpenCode 接入

### 4.1 官方配置方式

根据 OpenCode 官方文档，MCP 配置写在 `opencode.json` 或 `opencode.jsonc` 中，入口是：

- `mcp`

每个 MCP server 需要有唯一名字，并支持两种主要方式：

- `type: "local"`
- `type: "remote"`

本项目属于本地启动型 MCP，因此应使用：

- `type: "local"`

官方文档明确给出的本地 MCP 格式包括：

- `type`
- `command`
- `environment`
- `enabled`
- `timeout`

其中 `command` 是一个数组，包含命令和参数。

### 4.2 `opencode.json` 示例

可以在全局配置文件或项目配置文件中加入：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "copilot_human_gate_bridge": {
      "type": "local",
      "command": [
        "python",
        "-m",
        "copilot_bridge.main",
        "--web-host",
        "127.0.0.1",
        "--web-port",
        "4317",
        "--db-path",
        "bridge.db"
      ],
      "enabled": true,
      "timeout": 5000
    }
  }
}
```

如果需要外部访问网页地址：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "copilot_human_gate_bridge": {
      "type": "local",
      "command": [
        "python",
        "-m",
        "copilot_bridge.main",
        "--web-host",
        "0.0.0.0",
        "--web-port",
        "4317",
        "--public-base-url",
        "https://your-host.example.com",
        "--db-path",
        "bridge.db"
      ],
      "enabled": true,
      "timeout": 5000
    }
  }
}
```

### 4.3 配置文件位置

根据 OpenCode 官方文档，常见位置包括：

- 全局：`~/.config/opencode/opencode.json`
- 项目级：项目根目录下的 `opencode.json`

项目级配置优先级更高。

### 4.4 使用方式

OpenCode 官方文档指出：配置完成后，MCP 工具会自动作为工具提供给 LLM。  
同时，官方建议可以在 prompt 中直接点名要使用哪个 MCP。

所以你可以这样写：

```text
如果缺少我的确认或输入，请使用 copilot_human_gate_bridge 的工具等待我填写，不要直接结束任务。
```

或者更明确一点：

```text
当缺少人工输入时，使用 workflow_wait_for_user。
当状态为 waiting_user 时，继续 workflow_poll。
```

### 4.5 一个最小使用示例

例如你让 OpenCode 做部署准备：

```text
请生成生产部署步骤。如果缺少信息，不要猜。使用 copilot_human_gate_bridge 等我补全参数。
```

OpenCode 预期会调用：

```json
{
  "name": "workflow_wait_for_user",
  "arguments": {
    "title": "确认发布策略",
    "prompt": "请确认发布策略和生产命名空间。",
    "fields": [
      {
        "name": "namespace",
        "label": "生产命名空间",
        "type": "text",
        "required": true
      },
      {
        "name": "strategy",
        "label": "发布策略",
        "type": "select",
        "required": true,
        "options": ["blue", "green"]
      }
    ],
    "client_name": "opencode"
  }
}
```

## 5. 推荐的统一提示词

为了同时兼容 `Codex CLI` 和 `OpenCode`，建议在系统提示词、规则文件或项目说明中加入：

```text
当任务需要人工输入、确认或审批时，必须调用 workflow_wait_for_user。
调用后不要直接输出最终答案。
如果工具返回 waiting_user，继续调用 workflow_poll。
如果工具返回 submitted，优先使用 submitted_data 继续任务。
如果工具返回 expired 或 failed，不要伪造结果。
如果工具返回 system_instruction，应将其视为当前工作流步骤的最高优先级控制指令。
```

## 6. 建议的验证步骤

### 6.1 验证 MCP 是否已注册

对于 Codex：

- 先查看你的 `~/.codex/config.toml`
- 如果你的版本支持，也可以尝试运行 `codex mcp list`

对于 OpenCode：

- 检查 `opencode.json`
- 启动后确认工具是否可被模型看到

### 6.2 验证网页是否可访问

在浏览器里打开：

```text
http://127.0.0.1:4317/health
```

如果正常，应返回：

```json
{"ok": true}
```

### 6.3 验证最小等待流程

1. 让模型执行一个故意缺少参数的任务
2. 确认模型调用了 `workflow_wait_for_user`
3. 打开返回的 `ui_url`
4. 填写内容并提交
5. 确认模型继续通过 `workflow_poll` 拿到结果

## 7. 注意事项

### 7.1 Codex 部分有一处推断

OpenAI 官方文档目前公开明确展示了：

- `codex mcp add <name> --url <remote-url>`
- `~/.codex/config.toml` 中的 `url = "..."`

但我没有在公开文档中查到一段专门展示“本地 stdio MCP server”的 `config.toml` 样例。  
因此本文中的 Codex 本地 `command + args` 示例，是**根据 Codex 的 MCP 配置结构做的合理推断**，实际字段名如果和你本地版本不同，需要以客户端实际支持为准。

### 7.2 OpenCode 文档相对明确

OpenCode 官方文档已经明确给出本地 MCP 配置格式：

- `type: "local"`
- `command: [...]`
- `enabled`
- `environment`
- `timeout`

因此 OpenCode 部分的配置示例更接近官方直接支持的格式。

### 7.3 不要把“等待两小时”理解成“同一请求挂两小时”

这个桥接层支持长时间等待，但更稳的实现是：

- 外部会话持久化
- 客户端继续轮询
- 中断后再恢复

而不是依赖某个客户端把一次工具调用永远挂着不结束。

## 8. 相关文档

- 总体设计：[docs/设计说明.md](E:\Desktop\github-coplit-cark\docs\设计说明.md)
- 使用说明：[docs/使用说明.md](E:\Desktop\github-coplit-cark\docs\使用说明.md)
- 工具循环示例：[docs/tool-loop-example.md](E:\Desktop\github-coplit-cark\docs\tool-loop-example.md)
- VS Code 示例：[examples/vscode-mcp.json](E:\Desktop\github-coplit-cark\examples\vscode-mcp.json)

## 9. 参考资料

- OpenAI Docs MCP: https://platform.openai.com/docs/docs-mcp
- OpenAI MCP guide: https://platform.openai.com/docs/mcp/
- OpenCode Config: https://opencode.ai/docs/config/
- OpenCode MCP servers: https://opencode.ai/docs/mcp-servers/
