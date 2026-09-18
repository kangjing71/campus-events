# 校园共创：校园活动全流程 MVP

Python 3.10+、SQLite、原生 HTML/CSS/JavaScript。模型输出使用 `jsonschema` 校验；前端图标和二维码库已打包为本地文件。

**接入五个业务 Agent：阅读 [AGENT_SETUP.md](AGENT_SETUP.md)。** 每个角色拥有独立的接口、模型、密钥、prompt 和只读工具权限；默认 prompt 已提供。

## 启动

```bash
cd /home/lzh/campus-events
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py --port 8765
```

当前体验环境已具备依赖，也可以直接启动：

```bash
python3 server.py --port 8765
```

终端输出含负责人密钥的工作台地址。首次打开后，密钥保存在当前浏览器会话中，URL 中的密钥会移除。报名入口 `/join/<活动ID>` 无需负责人密钥。服务默认只监听本机；局域网演示时使用 `--host 0.0.0.0`，并通过可被参与者访问的 IP 地址打开工作台再生成二维码。

使用 `python3 server.py --port 8765 --demo` 可在空数据库中创建一份待确认示例策划，报名和反馈数据均为零。

## 演示流程

1. 新建活动，填写活动信息，也可点击“填入示例需求”。示例只填充需求，不伪造报名数据。
2. 生成并审阅策划，包括两条 Timeline、预算、分工、风险和目标；可修改需求或方案正文。
3. 确认策划，生成宣传，预览并确认文案和海报。确认后开放本站报名。
4. 在报名管理打开参与者入口，填写真实报名；可复制链接、查看二维码、导出 CSV。
5. 开启现场签到。参与者用报名凭证签到，或负责人在名单中签到。
6. 提交现场反馈；提出流程顺延建议，审批后才更新 Timeline。
7. 结束活动，填写活动后反馈，生成并确认复盘，再确认活动总结并归档。

数据保存在项目目录的 `events.sqlite3`，重启服务后保留。可用 `EVENT_DB` 指向其他数据库文件。请不要提交包含报名数据或管理员密钥的数据库。

## 六个 Agent 与共享上下文

`server.py` 中 `Orchestrator` 管理状态和权限，五个业务角色通过 `agents/runtime.py` 独立调用模型，`agents/contracts.py` 定义输出结构。`prompts/` 保存各角色可编辑的 prompt。SQLite 保存共享活动上下文和独立调用日志。本 MVP 使用单进程部署；模型调用在写锁外运行，提交时重新检查版本。

```text
DRAFT → WAITING_PLAN_CONFIRMATION → PLAN_CONFIRMED
→ WAITING_PUBLICITY_CONFIRMATION → REGISTRATION_OPEN
→ LIVE → FEEDBACK → WAITING_REVIEW_CONFIRMATION
→ WAITING_RECAP_CONFIRMATION → COMPLETED
```

所有业务阶段约束都在后端校验。正式策划确认时保存原始快照；现场调整需另行批准；所有关键动作写入日志。生成复盘时冻结反馈入口，防止报告与后续输入不一致。

负责人操作请求必须携带最新活动的 `expected_version`。其他页面修改或新增报名导致版本变化时，需刷新并重新核对，避免审批过期内容。

## 生成模式

每个角色可单独运行在规则模式或模型模式。未配置接口时使用明确标识的规则模式；配置后，策划补问和完整方案、两种宣传文案、报名分析和答疑、现场分析和调整建议、复盘分析均通过对应模型生成。模型失败不静默降级。

配置入口为 `.env` / `agents.json`，支持 chat_completions 接口和约定的自定义 JSON Agent 接口。所有模型输出先经 JSON Schema 和业务校验，再进入原有审批流程。详见 [接入指南](AGENT_SETUP.md)。

调用链已使用本地模拟模型验证，尚未使用真实供应商凭据联调。规则模式不会理解任意自然语言约束；真实模型的语义质量也需用实际活动验收。

## API

负责人接口需要 `Authorization: Bearer <终端输出的密钥>`：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET / POST | `/api/events` | 列表 / 新建活动 |
| GET | `/api/events/:id` | 活动完整上下文 |
| POST | `/api/events/:id/actions/:action` | 执行业务动作及审批 |
| GET | `/api/events/:id/export` | 下载报名 CSV |
| GET | `/api/agents` | 查看五个角色的脱敏配置状态 |
| POST | `/api/agents/:role/test` | 真实模型连通与 JSON 输出测试 |
| GET / POST | `/api/agents/:role/playground` | 独立测试样例 / 运行单个角色的业务测试 |
| GET | `/api/agent-runs` | 最近 100 次调用状态、耗时和工具记录 |
| GET | `/api/public/:id` | 脱敏活动信息 |
| POST | `/api/public/:id/register` | 报名并获得凭证 |
| POST | `/api/public/:id/ticket` | 凭凭证查询自己的报名及答复 |
| POST | `/api/public/:id/checkin` | 凭凭证签到 |
| POST | `/api/public/:id/feedback` | 凭凭证提交反馈 |

## 验证与前端资源

```bash
python3 -m unittest discover -s tests -v
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

浏览器测试会自行启动独立的临时数据库服务，验证完整生命周期及移动端报名，不污染工作台数据库。

## MVP 边界

- 外部微信公众号、社交平台、邮件和短信未接入，文案、海报和提醒需要负责人手动发布；无后台定时任务。
- 现场签到是报名凭证自助签到，不校验 GPS 或地理围栏。
- 当前为单负责人密钥，无多用户角色、密码找回或组织隔离；适合本机/可信局域网演示，不应直接暴露到公网。
- 未实现照片上传、自动二次宣传或正式发布后的策划重开。现场反馈分析由负责人触发，模型模式可归纳问题与给出证据。
- 现场支持顺延选定环节及后续时间；方案正文可编辑，其他结构化修改在确认前通过重新生成完成。
- 完整复盘评分按参与者去重，活动后有效评分优先；没有评分显示“暂无数据”。

校园图片来自 Unsplash：`https://images.unsplash.com/photo-1523580494863-6f3031224c94`。图标使用 Lucide（ISC），二维码使用 qrcode（MIT）；依赖许可见 `licenses/`。
