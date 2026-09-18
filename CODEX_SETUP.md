# 本机 Codex 接口

五个角色共用 `agents.json` 的 `defaults.protocol = codex_exec`，仍然独立加载各自的 `prompts/*.md`。无需填写五套 API Key。空 `model` 使用服务运行用户的 Codex 默认模型；显式填写则覆盖默认值。

当前服务用户为 `lzh`。实际使用从当前 VS Code 安装的同版 CLI（`/home/lzh/.local/lib/campus-events/codex`），而不是读取另一套配置的 Snap CLI。模型为 `gpt-6-astra`。

经负责人明确授权，当前 ChatGPT 登录已复制到专用目录 `/home/lzh/.local/share/campus-events-codex`（目录 0700、凭据 0600）。该目录仅供服务用户使用，不在项目或前端中保存凭据。`agents.json` 的 `codex_home` 指定此目录，`codex_proxy` 指向本机代理 `http://127.0.0.1:7897`；代理需保持运行。更换机器时应更新这些路径和代理设置，并重新登录。

检查登录状态：

```bash
sudo -u lzh env CODEX_HOME=/home/lzh/.local/share/campus-events-codex /home/lzh/.local/lib/campus-events/codex login status
```

如凭据失效，使用同一命令将 `login status` 改为 `login` 完成服务专用登录。不要只在 Snap Codex 中登录，其配置目录与此服务不同。

每次请求通过 stdin 传入 prompt、业务上下文和只读数据快照。采用独立临时工作目录、read-only sandbox、禁止审批、ephemeral 会话，关闭 shell、浏览器、应用插件和 hooks。不要为此服务的 Codex 配置额外 MCP 服务。临时结果在请求结束后清理；模型调用仍会使用当前账户的额度，并将所需业务上下文发送给模型服务。

默认单次 CLI 超时 180 秒，最多进行一次输出格式修复。返回结果仍经过现有 JSON Schema 和业务规则校验。失败不会回退为假模型结果，不会自动批准或发布活动。

独立测试入口为 `/agents/planning`、`/agents/publicity`、`/agents/registration`、`/agents/onsite`、`/agents/review`。使用原负责人访问密钥登录后，可分别测试连接和效果。

兼容原来的 `chat_completions` 和 `json` 协议。角色级 `PLANNING_PROTOCOL` 等环境变量可覆盖默认协议；HTTP 模式仍需配置相应 URL、模型和密钥。测试套件显式使用模拟 HTTP 协议，不消耗 Codex 额度。

真实验收（消耗账户额度，执行五次连接测试和八个业务效果测试，不写入正式活动）：

```bash
sudo -u lzh python3 verify_codex.py --live
```

报告默认保存到 `/tmp/campus-codex-live-report.json`，包括真实结果、耗时和调用记录。常规 `python3 -m unittest discover -s tests` 不消耗额度。

Codex 非交互模式文档：https://developers.openai.com/zh-Hans/docs/non-interactive-mode
