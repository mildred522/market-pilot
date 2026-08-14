# 餐饮门店分析 Agent

一个面向餐饮小店的经营分析 Agent MVP，分为两个业务模块：

- 开店前潜力分析：根据投资预算、租金、商圈、品类和加盟信息判断项目能不能开。
- 开店后经营诊断：根据订单、菜品成本和评论数据判断门店为什么不赚钱，以及下一步怎么改。

## 当前进度

固定轮次 MVP 与 Agent 核心演进计划已经完成：

- `backend/`：FastAPI 后端，包含 `/health` 健康检查。
- `backend/app/tools/`：保本线、营收、菜品矩阵和评论主题等确定性分析工具。
- `backend/app/agent_runtime/`：结构化 Plan-and-Execute 运行时，包含模型客户端、工具白名单、动态规划、统一工具执行契约、证据引用校验和确定性降级。
- `backend/app/observability/`：安全运行追踪，关联 request/run/analysis ID，记录计划、工具、模型统计、记忆 ID 和降级原因。
- `backend/app/pre_open/`：开店可行性领域规则与类型化结果。
- `backend/app/memory/`：基于 SQLite/SQLAlchemy 的结构化会话、项目档案、受限上下文和历史指标比较，不依赖向量数据库。
- `backend/app/location/`：百度 POI 候选生成、圈层采集、机会评分、可信度评估、快照复用和降级处理。
- `backend/app/agents/`：确定性报告与兼容降级逻辑。
- `frontend/`：Next.js + React + TypeScript 前端，包含业务入口、开店前问卷、开店后 CSV 上传、自动字段映射和诊断报告页。
- `frontend/components/`：指标卡、营收图、菜品矩阵、评论主题、风险、证据和行动清单组件。
- `frontend/app/demo/`：面试演示入口。
- `docs/`：业务指标体系、系统架构、MVP 架构方案和固定轮次实施计划。

## 本地运行

### Windows 一键启动器

双击 `dist/MarketPilotLauncher.exe`，然后点击“启动并打开”。启动器会检查运行环境、启动前后端、等待服务就绪并打开浏览器。关闭启动器时可选择是否同时停止服务。

首次使用仍需安装 Python、Node.js 及项目依赖。需要重新生成启动器时，在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\launcher\build-launcher.ps1
```

启动器需要 Windows x64 和 .NET 8 Desktop Runtime，但不会内置 Python、Node.js、依赖、数据库或 API 密钥。应将其保留在当前项目的 `dist` 目录中；如需放到其他位置，可通过 `MARKET_PILOT_ROOT` 环境变量指定项目根目录。

### 后端

```powershell
cd backend
python -m pip install -r requirements.txt
python -m pytest
python -m uvicorn app.main:app --reload
```

健康检查：

```text
GET http://127.0.0.1:8000/health
```

预期响应：

```json
{ "status": "ok" }
```

### 配置 Agent 模型

后端支持 OpenAI-compatible Chat Completions 接口。复制 `.env.example` 中的配置到本地 `.env` 或进程环境变量：

```text
AGENT_LLM_PROVIDER=openai-compatible
AGENT_LLM_BASE_URL=https://api.openai.com/v1
AGENT_LLM_API_KEY=your-server-side-key
AGENT_LLM_MODEL=your-model-name
AGENT_LLM_PLANNER_MODEL=optional-planner-model
AGENT_LLM_SYNTHESIZER_MODEL=optional-synthesizer-model
AGENT_LLM_FOLLOWUP_MODEL=optional-followup-model
AGENT_LLM_TIMEOUT_SECONDS=75
```

`AGENT_LLM_API_KEY` 和基础模型均存在时启用模型路径；三个角色模型是可选覆盖值，留空时使用基础模型。缺少配置、请求失败、输出不符合 Schema 或引用不存在的指标时，自动退回确定性分析。也可以在本地工作台配置模型和百度地图密钥；密钥由后端使用，并通过 Windows DPAPI 加密保存，不写入前端持久化存储。

前端不在默认 3000 端口运行时，通过逗号分隔的 `CORS_ORIGINS` 显式加入实际浏览器来源；不要使用通配符来源。

经营报告支持有限 ReAct 追问：模型最多进行 4 轮，只能调用读取指标、列出指标分区、列出指标路径和读取报告摘要等只读工具；不能修改数据、读取任意文件或重新调用百度 API。

### 前端

```powershell
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://localhost:3000
```

### Agent 离线评测

评测集使用脚本化模型响应和合成业务数据，不需要配置外部模型或地图密钥：

```powershell
cd backend
python -m scripts.run_agent_evals
```

命令会运行 30 条经营规划与报告追问用例，在 `outputs/evals/` 生成 JSON 和 Markdown 报告。当前 CI 安全门禁检查证据引用、虚构数值、无依据的比较性结论和必要的数据不足声明，并对聚焦模式的工具精确率、召回率和严格匹配率执行回归阈值。

已验证的关键指标与 Phase 1 对比见 [Agent 面试评估证据](docs/interview-evidence.md)。实时模型评估默认关闭；显式开启方式和成本单价配置见 [Agent 评测基线](docs/agent-evaluation.md#opt-in-live-evaluation)。

### 演示路径

推荐入口：

```text
http://localhost:3000/demo
```

完整五分钟讲解顺序见 [Demo 脚本](docs/demo-script.md)，覆盖 full/focused 规划、证据追问、结构化记忆、缺基准拒答、安全降级和统一能力入口。

也可以直接访问：

1. `http://localhost:3000/pre-open`：提交默认问卷后点击“查看完整报告”。
2. `http://localhost:3000/operating`：点击“生成样例经营诊断”后点击“查看完整报告”。

经营诊断也支持上传真实 CSV：依次上传订单、菜品成本和评论文件，确认系统建议的字段映射，填写租金、人工、水电、营销、其他固定成本、可用现金、外卖佣金率和单均包材成本，再点击“分析已上传数据”。报告会计算实际毛利率、保本营业额、保本订单数、月利润投影和现金支撑期，并按堂食、外卖等渠道对比营收、客单价、渠道费用和贡献利润。CSV 支持 UTF-8、UTF-8 BOM 和 GB18030 编码，单文件最大 5 MB。

### 完整经营样本

`outputs/operating-demo/` 提供一组可直接上传的中文表头样本：

1. `orders_demo.csv`：订单 CSV，包含 30 个营业日、堂食/美团/饿了么、午晚时段及折扣实收。
2. `menu_items_demo.csv`：菜品成本 CSV，包含售价和单位成本。
3. `reviews_demo.csv`：评论 CSV，包含评分和经营问题关键词。
4. `market_pilot_operating_demo.xlsx`：上述数据的 Excel 查阅版，附上传说明和预期分析信号。

建议沿用页面默认成本假设进行演示。该样本会呈现后半月营收下降、6 月 24 日异常低营收、午市峰值、外卖渠道贡献、折扣利润压力及中差评主题。

## 项目亮点

- 两个业务模块清晰分流：开店前看潜力和风险，开店后看经营问题和整改。
- 数值指标由 pandas/SQL 工具计算，不让 LLM 猜营业额、毛利、客单价。
- 轻量 Plan-and-Execute Agent：路由、规划、工具执行、总结、证据校验。
- 经营分析支持完整体检和聚焦问题两种模式；聚焦模式只调用一至四个必要工具，并允许一次受限重规划。
- 工具统一返回状态、证据、耗时和安全错误码；可选工具失败时允许带警告的局部结果，必需工具失败时停止综合。
- 报告追问保存公开问答，最多读取最近 6 条消息，并可通过只读工具比较同一项目的历史指标。
- 百度 POI 支持自动推荐候选商圈和手动铺位分析，并明确区分机会评分与数据可信度。
- 报告页明确区分结论、指标、证据、风险和行动清单。
- 使用 TypeScript 约束前端表单、API 响应、图表数据和报告结构。

## MVP 暂不实现

- 登录注册和复杂权限。
- 真实外卖平台 API。
- 真实客流、营业额和外卖平台数据自动采集。
- 合同全文法律审查。
- 多门店集团管理。
- 自动 PDF 导出。

## 架构文档

- [指标体系](docs/restaurant-agent-analysis-indicators.md)
- [系统架构](docs/restaurant-agent-architecture.md)
- [MVP 架构方案](docs/restaurant-agent-mvp-architecture-plan.md)
- [设计文档索引](docs/design/README.md)
- [项目交付历史](docs/design/delivery-history.md)
- [API 契约](docs/api-contract.md)
- [Agent 评测基线](docs/agent-evaluation.md)
- [Agent Memory](docs/agent-memory.md)
- [Agent 核心设计](docs/agent-core-design.md)
- [Agent 面试评估证据](docs/interview-evidence.md)
- [ADR：结构化记忆不用 RAG](docs/decisions/structured-memory-without-rag.md)
- [ADR：受策略约束的规划](docs/decisions/policy-constrained-planning.md)
- [Demo 脚本](docs/demo-script.md)
