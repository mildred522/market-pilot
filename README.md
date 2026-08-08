# 餐饮门店分析 Agent

一个面向餐饮小店的经营分析 Agent MVP，分为两个业务模块：

- 开店前潜力分析：根据投资预算、租金、商圈、品类和加盟信息判断项目能不能开。
- 开店后经营诊断：根据订单、菜品成本和评论数据判断门店为什么不赚钱，以及下一步怎么改。

## 当前进度

固定 7 轮 MVP 方案已推进到 Round 7：

- `backend/`：FastAPI 后端，包含 `/health` 健康检查。
- `backend/app/tools/`：保本线、营收、菜品矩阵和评论主题等确定性分析工具。
- `backend/app/agent_runtime/`：结构化 Plan-and-Execute 运行时，包含模型客户端、工具白名单、动态规划、证据引用校验和确定性降级。
- `backend/app/agents/`：确定性报告与兼容降级逻辑。
- `frontend/`：Next.js + React + TypeScript 前端，包含业务入口、开店前问卷、开店后 CSV 上传、自动字段映射和诊断报告页。
- `frontend/components/`：指标卡、营收图、菜品矩阵、评论主题、风险、证据和行动清单组件。
- `frontend/app/demo/`：面试演示入口。
- `docs/`：业务指标体系、系统架构、MVP 架构方案和固定轮次实施计划。

## 本地运行

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
AGENT_LLM_TIMEOUT_SECONDS=20
```

`AGENT_LLM_API_KEY` 和 `AGENT_LLM_MODEL` 均存在时，经营诊断使用结构化 AI Planner 和 Synthesizer；缺少配置、请求失败、输出不符合 Schema 或引用不存在的指标时，自动退回确定性分析。密钥只允许配置在后端环境中。

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

### 演示路径

推荐入口：

```text
http://localhost:3000/demo
```

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
- 报告页明确区分结论、指标、证据、风险和行动清单。
- 使用 TypeScript 约束前端表单、API 响应、图表数据和报告结构。

## MVP 暂不实现

- 登录注册和复杂权限。
- 真实外卖平台 API。
- 自动地图/竞品爬取。
- 合同全文法律审查。
- 多门店集团管理。
- 自动 PDF 导出。

## 架构文档

- [指标体系](docs/restaurant-agent-analysis-indicators.md)
- [系统架构](docs/restaurant-agent-architecture.md)
- [MVP 架构方案](docs/restaurant-agent-mvp-architecture-plan.md)
- [固定轮次实施计划](docs/superpowers/plans/2026-07-04-restaurant-agent-mvp-rounds.md)
- [API 契约](docs/api-contract.md)
- [Demo 脚本](docs/demo-script.md)
