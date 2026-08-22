# 领域工作流渐进式披露方案

## 1. 目标

经营 Planner 不再一次读取全部 Tool 的指标输出契约。模型只负责选择业务工作流和分析维度，
程序负责把选择确定性展开为底层 Tool，并保持现有 EvidencePack、校验、预算和 Replan 机制。

验收目标：

- Planner 静态目录字符数至少下降 80%；
- 不增加 Planner 模型调用轮次；
- focused 模式仍限制为 1 至 4 个 Tool；
- 必需工具召回率、Tool exact-set 和安全门禁不低于当前基线；
- full 模式行为保持不变。

## 2. 三级披露

```text
L0 Capability
  pre_open_feasibility / location_analysis / operating_diagnosis
        |
L1 Workflow cards
  revenue_trend / profit_diagnosis / menu_optimization /
  customer_experience / promotion_channel
        |
L2 Policy expansion
  selected workflow + dimensions -> concrete tools
        |
L3 Evidence contracts
  only executed metrics -> EvidencePack -> Synthesizer
```

Planner 只接收工作流名称、业务说明、适用表达和可选维度，不接收 Tool 的完整
`output_contract`。工作流到 Tool 的映射不暴露给模型，防止模型绕过策略层。

## 3. 工作流定义

| Workflow | 默认维度 | 可选维度 |
| --- | --- | --- |
| `revenue_trend` | revenue | revenue -> revenue, trend -> time, channel -> channel |
| `profit_diagnosis` | survival | survival -> survival, trend -> time, channel -> channel, promotion -> discount, product -> menu |
| `menu_optimization` | product | product -> menu, customer -> reviews, promotion -> discount, revenue -> revenue |
| `customer_experience` | customer | customer -> reviews, time -> time, product -> menu |
| `promotion_channel` | promotion + channel | revenue -> revenue, promotion -> discount, channel -> channel, survival -> survival |

显式维度覆盖默认维度，因此“只看高峰时段”可以只展开 time Tool，不会因工作流默认值额外
执行 revenue。工作流只声明业务依赖。Tool 输入仍由 `OperatingToolContext` 注入，模型不能构造 DataFrame、
文件路径或底层参数。

## 4. 兼容策略

`AgentPlan` 增加可选的 `workflow` 与 `dimensions`，保留原 `tools` 字段：

- 新 Planner 优先返回 workflow 决策；
- 旧脚本化客户端和历史模型仍可返回 Tool 列表；
- Policy 只接受两种形式之一，并统一生成最终 Tool 列表；
- full 模式始终由 Policy 补齐全部可用核心 Tool；
- workflow 非法、维度非法或展开超过 4 个 Tool 时，回退到确定性路由。

该兼容窗口允许评测 fixture、实时模型和 API 平滑迁移。稳定后可以删除 Planner 直接选择
Tool 的旧路径，但 Tool Registry 和执行器不需要变化。

## 5. 可观测性与评测

Trace 增加 workflow、dimensions 和 disclosure 统计：候选工作流数、Planner 目录字符数、
旧完整目录字符数及压缩比例。评测同时保留工具精确集合指标，并增加：

- workflow selection accuracy；
- required-tool recall；
- planner catalog reduction；
- Planner input tokens、总模型调用数、P95 延迟和降级率。

离线安全门禁继续使用脚本化模型。真实 DeepSeek A/B 评测比较旧 Tool Catalog 与渐进式
Workflow Catalog，只有质量不退化且 Token/延迟改善时才移除兼容路径。
