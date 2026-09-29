# 电商迁移 M0：领域边界与平台层基线

> 状态：2026-09-29 已执行。M0 只建立边界和接口骨架，不代表电商业务功能已经实现。

## 决策

Market Pilot 从餐饮经营诊断向**平台无关的电商经营 Agent**演进。餐饮能力暂不删除，作为独立的 legacy restaurant domain；电商能力从独立的 `commerce` domain 开始，不把任何公开数据集或平台字段写进核心模型。

电商第一条业务链路为：商品经营分析、趋势与热点发现、商品结构诊断、已售商品优化、待测试商品选品和测试计划。产品支持两种分析模式：

- `merchant`：只在当前组织、店铺、项目和快照范围内分析商家数据。
- `benchmark`：分析公开或演示数据，用于能力验证和展示，不写入商家私有记忆或计划。

交互模式分为：

- `talk`：日常信息获取、指标解释和自然语言建议，默认只读。
- `plan`：生成、审批、激活、跟踪和复盘长期计划；权限由服务端控制，第一版不执行外部业务动作。

## 领域边界

通用 Agent 平台继续提供认证会话、资源授权、指标注册、证据包、运行追踪、预算、记忆、知识审计和评测能力。电商领域只负责商品、SKU、订单、订单明细、候选池、数据源、快照、指标和工作流。

```text
User → Organization → Store → Project → Snapshot → Analysis / Plan
```

一个商家项目只绑定一个 Store。快照不可变；分析固定引用生成时的快照；计划通过版本化复盘更新，不因新数据自动漂移。

电商核心不得依赖餐饮专属对象，例如 `PreOpenInput`、选址、堂食/外卖、菜品成本、餐饮保本线或 `MenuItem`。餐饮 API 和数据库表在迁移完成前保持不变。

## 已落地的接口骨架

- `backend/app/commerce/contracts.py` 定义 `merchant` / `benchmark`、`talk` / `plan` 和数据能力枚举。
- `CommerceScope` 表达项目、店铺、模式和快照边界，并拒绝没有店铺范围的商家分析。
- `CapabilityAvailability` 表达支持、部分支持和不支持，避免用零值或模型猜测补齐成本、库存、流量等缺失能力。
- `CommerceSourceAdapter` 定义数据源检查和规范化接口；当前已实现 Olist 的第一阶段适配，先把支持文件写入 source-specific staging，再投影订单、订单行和商品到 canonical sales 数据，尚未完成卖家/评价/履约实体或其他平台适配器。
- `backend/app/commerce/canonical/` 定义平台无关的商品、SKU、订单和订单明细记录。
- `CommerceSnapshot` 保存不可变的数据版本元数据；`check_capability` 为后续指标和工作流提供能力降级入口。

这些接口暂不挂入现有 API 路由，也不改变当前餐饮 Agent 的路由行为。

## M0-M3 基线与验收

- Git 基线：`56915d9`（2026-09-29 本地与 `origin/main` 一致）。
- 既有文档记录的回归基线：494 passed、2 skipped；Agent Eval 53/53。本阶段不重写或降低旧基线。
- 新增接口只做契约级测试，不能要求数据库、外部平台或网络数据。
- M1 只完成内存中的标准契约和 Snapshot 元数据，不代表已经实现导入、持久化或指标计算。
- M2 增加标准四表 CSV 包的文件级校验、主外键质量检查、内容哈希和内存 Dataset；导入失败不会生成可用 Snapshot。
- M3 增加确定性商品销售汇总、等长度窗口趋势比较和可解释热点标签；指标不依赖 LLM，也不生成黑盒综合分数。
- M4 增加只读 Talk 工具白名单；工具只能读取已校验 Dataset，不能创建 Plan、写入记忆或执行外部动作。
- M5 增加 Talk 请求/响应策略和确定性问题路由；Talk 可解释结果，但不会隐式升级为长期计划。
- M6 增加独立的 `POST /commerce/talk` 入口和进程内快照注册表。入口先校验当前用户对 Project 的所有权，再按明确的 `snapshot_id` 读取不可变 Dataset；没有快照时不允许运行。当前只开放 `benchmark` API 路径，`merchant` 会明确返回未就绪，不把缺少 Store 资源模型伪装成商家授权。
- M7 增加独立的商品经营 Plan 草案和审批链路：`POST /commerce/plans`、`GET /commerce/plans/{id}`、`POST /commerce/plans/{id}/approve`。当前复用已有 `is_admin` 作为 Plan 权限门禁；普通用户即使拥有自己的 Project 也只能使用 Talk。Plan 固定引用 Snapshot 和证据，不会自动改价、采购、投放或写入外部平台。
- M8 将公开 Benchmark Snapshot 从进程内 Registry 迁移到 SQLite 持久化。只允许本地 `backend/scripts/import_commerce_benchmark.py` 导入已校验的标准四表 CSV，API 只读数据库快照；同一 `snapshot_id` 的重复导入必须内容一致，内容冲突直接拒绝。
- 旧餐饮页面、API、认证隔离和知识审计不因 `commerce` 包的加入而改变。
- 已完成的顺序为：标准数据契约与快照 → 文件级导入与质量报告 → 确定性商品指标 → Talk 工具与策略层 → Plan → Benchmark Snapshot 持久化 → DuckDB 分析 artifact → Olist staging 与第一阶段字段映射。后续实现顺序为：履约/评价诊断 → 电商工作台 → Organization/Store 授权；平台适配器按需要接入。

## 明确不做

当前不实现 Olist 完整适配、其他平台连接器、自然语言 SQL、图记忆、Temporal、OIDC、自动采购/改价/投放，也不把现有餐饮模型改名为电商模型。M6/M8 不提供公开 Dataset 上传或注册接口；Benchmark 数据必须通过本地导入脚本进入数据库，避免任意请求把数据注入服务进程。M7 暂不实现多角色 RBAC、计划执行器、计划自动复盘和商家 Store 授权；`is_admin` 只是当前原型阶段的最小权限门禁，不是最终 ToB 权限模型。
