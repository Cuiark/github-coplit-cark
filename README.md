# Copilot Human Gate Bridge 部署说明

## 1. 项目作用

这个项目会在本机启动一个 MCP 服务，并同时提供一个网页输入面板。

核心用途：

- Codex 在一次长会话里调用 MCP 工具
- 当缺少人工输入时，弹出一个网页填写入口
- 用户在网页中提交内容后，工作流继续执行

本地默认地址：

- 面板首页：`http://127.0.0.1:4317/`
- MCP 接口：`http://127.0.0.1:4317/mcp`
- 健康检查：`http://127.0.0.1:4317/health`

## 2. 运行要求

- Windows
- Python 可用，命令行能执行 `python`
- 已安装并可使用 Codex

## 3. 在一台新机器上部署

### 3.1 拷贝项目

把整个项目目录拷贝到目标机器，例如：

```powershell
D:\copilot_bridge
```

### 3.2 启动本地服务

进入项目根目录后执行：

```powershell
start_bridge.bat
```

如果启动成功，会看到：

- Dashboard: `http://127.0.0.1:4317/`
- MCP URL: `http://127.0.0.1:4317/mcp`

### 3.3 注册到 Codex

执行：

```powershell
install_codex_mcp.bat
```

这个脚本会把下面这段配置写入 Codex：

```toml
[mcp_servers.copilot_human_gate_bridge]
url = 'http://127.0.0.1:4317/mcp'
startup_timeout_sec = 30
```

然后重启 Codex。

### 3.4 验证

执行：

```powershell
codex mcp list
```

你应当看到：

- `copilot_human_gate_bridge`
- `http://127.0.0.1:4317/mcp`
- `enabled`

再访问：

- `http://127.0.0.1:4317/health`

如果正常，应返回 JSON。

## 4. 常用脚本

### 4.1 启动服务

```powershell
start_bridge.bat
```

作用：

- 启动 bridge 服务
- 使用本地 `bridge-runtime.db`
- 输出日志到 `.runtime` 目录

### 4.2 停止服务

```powershell
stop_bridge.bat
```

作用：

- 停止监听 `127.0.0.1:4317` 的 bridge 进程

### 4.3 安装 Codex MCP 配置

```powershell
install_codex_mcp.bat
```

### 4.4 卸载 Codex MCP 配置

```powershell
uninstall_codex_mcp.bat
```

### 4.5 安装开机自启

```powershell
install_startup.bat
```

作用：

- 登录 Windows 后自动调用 `start_bridge.bat`

### 4.6 卸载开机自启

```powershell
uninstall_startup.bat
```

作用：

- 删除开机启动项

## 5. 推荐使用方式

先启动服务，再打开 Codex。

推荐顺序：

1. `start_bridge.bat`
2. `install_codex_mcp.bat`
3. 重启 Codex
4. `codex mcp list`

## 6. 提示词建议

如果希望模型在缺少人工输入时不要直接结束会话，建议在系统提示词里明确要求：

- 优先使用 `workflow_wait_until_submitted`
- 非阻塞场景再使用 `workflow_wait_for_user` + `workflow_poll`
- 在任务真正完成前不要过早结束

可直接参考：

- `examples/workflow-session-system-prompt.txt`
