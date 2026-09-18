# 五个业务 Agent 接入指南

接入框架、前端入口、工具执行、结构校验和审批已实现。接下来主要填写各角色的接口配置，并按业务完善 `prompts/` 中的五份 prompt。

## 1. 填写接口和密钥

项目根目录的 `.env` 用于本机凭据；若文件不存在，可从 `.env.example` 创建。每个角色有三个配置项：

```dotenv
PLANNING_API_URL=https://your-provider.example/v1/chat/completions
PLANNING_MODEL=your-model
PLANNING_API_KEY=your-key

PUBLICITY_API_URL=
PUBLICITY_MODEL=
PUBLICITY_API_KEY=

REGISTRATION_API_URL=
REGISTRATION_MODEL=
REGISTRATION_API_KEY=

ONSITE_API_URL=
ONSITE_MODEL=
ONSITE_API_KEY=

REVIEW_API_URL=
REVIEW_MODEL=
REVIEW_API_KEY=
```

填写完整接口 URL，不要只填 `/v1` 基础地址。五个角色可以使用不同供应商，也可以共用一个接口和模型。共用配置可填写 `MODEL_API_URL`、`MODEL_NAME`、`MODEL_API_KEY`，各角色的非空配置优先。

`.env` 支持 `KEY=VALUE`、单/双引号包裹的值、独立注释行，不执行变量插值、命令或行尾注释。操作系统环境变量优先于 `.env`。`.env` 已加入 Git 忽略；密钥不会返回前端。

接口、prompt 和 `.env` 每次调用都会重新读取，修改文件后无需重启；刷新页面可更新角色状态。如果修改的是启动进程的环境变量，则需要重启进程。

## 2. 按角色修改 prompt

| 角色 | Prompt 文件 | 页面操作 |
| --- | --- | --- |
| 策划 | `prompts/planning.md` | 发送需求、补问、生成完整方案、按对话重新生成 |
| 宣传 | `prompts/publicity.md` | 生成宣传、按要求修改文案、生成和修改总结 |
| 报名 | `prompts/registration.md` | 分析报名情况、在提问弹窗生成答复草稿 |
| 现场 | `prompts/onsite.md` | 输入现场情况并生成分析及待审批调整 |
| 复盘 | `prompts/review.md` | 生成目标对比、分析发现和改进建议 |

已有默认 prompt 可直接试用。你可以调整风格、业务规则和判断标准；输出 JSON Schema 由代码自动追加，不需要在每份 prompt 中手写 schema。五个角色的任务分别是：

- planning：`collect_brief`、`generate_plan`
- publicity：`generate_publicity`、`generate_recap`
- registration：`answer_question`、`analyze_registration`
- onsite：`analyze_onsite`
- review：`generate_review`

策划对话会保存历史（最多 40 条），模型每次读取最近 20 条以及已提取的需求。必填字段是否齐全由后端检查，不能让模型跳过。已生成但未确认的方案在需求字段变化后会回到草稿状态，要求重新生成。

## 3. 选择接口协议

`agents.json` 管理每个角色的协议、超时、重试和 prompt 文件路径。`.env` 的非空接口配置优先于此文件。`defaults` 提供公共值，每个角色可以覆盖。

### 默认：chat_completions

适用于接受 `model` 和 `messages`、返回 `choices[0].message.content` 的接口。内容应为符合附带 schema 的 JSON 对象文本。

```json
{
  "model": "your-model",
  "messages": [
    {"role": "system", "content": "角色 prompt + 自动追加的 JSON Schema"},
    {"role": "user", "content": "包含 task 和 context 的 JSON 文本"}
  ],
  "temperature": 0.3
}
```

默认启用兼容的 `tools` / `tool_calls`。如果供应商不支持工具调用，在该角色配置中设置 `"tool_calling": false`；相同必要数据已包含在 context 中，角色仍可工作。

默认通过 prompt 要求 JSON，未强制发送 `response_format`。若供应商支持，可设置 `"response_format": "json_object"`。不要将仅支持其他原生协议的 URL 直接填入此模式。

### 自定义 Agent 服务：json

如果你的接口本身就是封装好的 Agent 服务，在该角色设置 `"protocol": "json"`。无需 model 名称，使用以下请求协议：

```json
{
  "agent": "registration",
  "task": "answer_question",
  "system_prompt": "完整角色指令及自动追加的输出格式",
  "context": {"facts": {"location": "大学报告厅"}, "question": "活动在哪里？"},
  "output_schema": {},
  "tools": {"get_event_facts": {"location": "大学报告厅"}}
}
```

接口直接返回业务 JSON 对象，不要再包一层 `data`、`result` 或 `choices`。例如：

```json
{
  "answer": "活动在大学报告厅举行。",
  "needs_human": false,
  "reason": "已确认活动地点",
  "evidence": ["大学报告厅"]
}
```

`tools` 是只读数据快照，不是让远端直接访问数据库。此协议不进行聊天式工具调用。修复请求会增加 `validation_error` 字段。两种协议都使用可选的 `Authorization: Bearer <key>`；其他认证方式、字段包装或原生供应商协议需要在服务端适配，不能仅靠修改 prompt 兼容。

## 4. 检查与验收

### 独立测试链接

每个角色均有独立页面，无需先创建活动或完成其他 Agent 的流程：

| 角色 | 本机链接 | 可测试的任务 |
| --- | --- | --- |
| 策划 | http://127.0.0.1:8765/agents/planning | 多轮需求补问、完整方案 |
| 宣传 | http://127.0.0.1:8765/agents/publicity | 招募文案、总结文案 |
| 报名 | http://127.0.0.1:8765/agents/registration | 问题答复、报名分析 |
| 现场 | http://127.0.0.1:8765/agents/onsite | 反馈分析、异常调整建议 |
| 复盘 | http://127.0.0.1:8765/agents/review | 样例指标对比、复盘建议 |

使用与工作台相同的负责人访问密钥登录。每页的“测试连接”只检查该角色接口；“运行效果测试”使用当前角色的真实业务方法和校验器生成结果，不会调用其他角色。

选择任务后可直接使用内置样例，也可编辑输入 JSON 和补充要求。策划补问可点击“继续补充需求”延续对话。右侧显示可读结果、原始 JSON、耗时、工具记录和输出来源，支持复制、下载和查看最近 10 条结果。历史仅保存在当前浏览器会话中，包含你填写的测试输入；不要将测试结果下载文件当作脱敏文件公开。

测试上下文与正式活动隔离：不创建活动、不保存方案、不修改时间线、不发送答复。服务器只保存不含输入正文的调用元数据，标记 `scope=playground`。试验样例中的报名路径 `/join/example-preview` 是占位值，不是有效的报名活动。

未配置模型时，连接测试不可用，效果按钮明确显示“预览规则结果”；它用于检查业务数据格式，不代表模型效果。模型模式接口失败不会切换成规则结果。

### 工作台检查

运行服务后，点击工作台右上角的设置图标打开“Agent 连接状态”：

1. 确认五个角色都显示“模型已配置”。这是配置状态，不代表接口已测试。
2. 逐个点击连接测试按钮；测试会真实调用对应接口并验证 `{"ok":true}`。
3. 用新活动测试策划补问与方案生成，再确认进入宣传。
4. 用参与者入口提交一个问题，在负责人页面生成并确认答复草稿。
5. 开启现场，输入异常情况并检查建议；审批前正式时间线应保持不变。
6. 收集反馈，生成复盘，核对证据和真实统计。

“最近调用”显示角色、任务、耗时、成功/失败；持久化日志还包含工具名称和 prompt 内容哈希，不保存请求原文、API Key 或上游错误响应。日志的“成功”指模型结果通过校验；如果随后发生版本冲突，页面会提示未写入，需要刷新重试。

## 5. 执行约束

- `mode: auto`：有接口则调用模型，否则明确使用规则模式。设置 `mode: model` 可以要求该角色必须配置接口；`mode: rules` 可临时关闭模型。
- 默认网络超时 45 秒；对 429、部分 5xx 和连接异常最多重试 1 次。401/403 不重试。
- 结构或业务校验失败会请求模型修复一次，仍无效则报错，不会降级为模板或保存半成品。
- 工具仅允许读取当前角色获准的数据快照；不提供发布、审批、删除或任意代码执行工具。单次任务工具轮数默认不超过 3。
- 模型可生成完整策划，但预算上限、时间顺序、目标人数关系由程序校验。现场调整的环节 ID、复盘证据 ID 也由程序验证。
- 报名答复是草稿，负责人确认后参与者才能看到；现场调整需要另外审批。
- 模型不修改报名、签到、评分或审批状态。统计由程序计算；模型文字的语义准确性仍需人审。
- 模型推理不持有数据库写锁。生成期间活动版本变化，返回 409，不覆盖新报名或反馈。
- 报名分析和反馈最多提供最近 200 条去标识样本，并提供全量统计。不会发送报名人的姓名、邮箱和凭证字段，但自由文本可能含参与者自行写入的信息。

## 6. 开发验证

```bash
python3 -m unittest discover -s tests -v
npm run test:e2e
```

测试启动本地模拟模型 HTTP 服务，验证五个独立接口与密钥、真实工具调用、JSON 修复、超预算和虚构证据拒绝、错误脱敏、并发写入冲突，以及手机/桌面完整流程。模拟模型不是实际大模型，不能证明供应商兼容性和业务生成质量；配置真实接口后需按第 4 节验收。

## 7. 运行中的服务

本机体验服务为临时 systemd 单元 `campus-events-mvp`，无开机自启。

```bash
sudo systemctl status campus-events-mvp
sudo systemctl restart campus-events-mvp
sudo systemctl stop campus-events-mvp
```

停止体验服务后，可在项目目录手动执行 `python3 server.py --port 8765`。已有 SQLite 数据和负责人密钥保持不变。
