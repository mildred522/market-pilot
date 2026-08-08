# API Contract

Base URL:

```text
http://127.0.0.1:8000
```

## GET /health

健康检查。

Response:

```json
{
  "status": "ok"
}
```

## POST /projects

创建门店项目。

Request:

```json
{
  "name": "社区粉面店",
  "stage": "pre_open"
}
```

`stage` 可选：

- `pre_open`
- `operating`

Response:

```json
{
  "id": 1,
  "name": "社区粉面店",
  "stage": "pre_open"
}
```

## POST /pre-open/analyze

提交开店前问卷并生成报告。

Request:

```json
{
  "project_id": 1,
  "category": "粉面",
  "city": "成都",
  "location_type": "community",
  "area_sqm": 60,
  "seats": 28,
  "monthly_rent": 18000,
  "total_investment": 280000,
  "own_capital": 150000,
  "debt_amount": 130000,
  "expected_daily_orders": 90,
  "expected_avg_order_value": 24,
  "expected_gross_margin": 0.62,
  "is_franchise": true,
  "franchise_fee": 68000,
  "competitor_count": 8,
  "storefront_visibility": "medium"
}
```

Response:

```json
{
  "analysis_id": 1,
  "project_id": 1,
  "stage": "pre_open",
  "summary": "当前项目需要重点核验租金、竞品密度和加盟投入是否匹配预估流水。",
  "metrics": {
    "estimated_daily_revenue": 2160,
    "estimated_daily_gross_profit": 1339.2,
    "daily_rent": 600
  },
  "risks": ["周边竞品密度较高，需要明确差异化"],
  "actions": ["开店前连续 3 天蹲点记录午市和晚市客流"]
}
```

## POST /files/upload

上传 CSV 文件、读取表头并返回自动字段映射建议。上传记录会保存到数据库，后续通过文件 ID 发起真实经营诊断。

Form fields:

- `project_id`
- `file_type`
- `file`

Response（系统会自动识别常见中英文表头）：

```json
{
  "file_id": 12,
  "project_id": 1,
  "file_type": "orders",
  "filename": "orders.csv",
  "columns": ["订单号", "下单时间", "渠道", "菜品名称", "数量", "实收金额"],
  "required_columns": ["order_id", "order_time", "channel", "item_name", "quantity", "actual_amount"],
  "suggested_mapping": {
    "order_id": "订单号",
    "order_time": "下单时间",
    "channel": "渠道",
    "item_name": "菜品名称",
    "quantity": "数量",
    "actual_amount": "实收金额"
  },
  "missing_columns": [],
  "row_count": 100
}
```

限制：仅支持 `orders`、`menu_items`、`reviews` 三种文件类型；文件必须是 CSV，支持 UTF-8、UTF-8 BOM、GB18030，单文件最大 5 MB。

## POST /operating/analyze

使用已上传并完成字段映射的三类 CSV 生成真实经营诊断。

Request：

```json
{
  "project_id": 1,
  "question": "分析订单、菜品和差评，找出当前经营问题",
  "orders": {
    "file_id": 12,
    "mapping": {
      "order_id": "订单号",
      "order_time": "下单时间",
      "channel": "渠道",
      "item_name": "菜品名称",
      "quantity": "数量",
      "actual_amount": "实收金额"
    }
  },
  "menu_items": {
    "file_id": 13,
    "mapping": {
      "item_name": "菜品名称",
      "category": "菜品分类",
      "sale_price": "售价",
      "unit_cost": "单位成本"
    }
  },
  "reviews": {
    "file_id": 14,
    "mapping": {
      "review_time": "评论时间",
      "rating": "评分",
      "content": "评论内容",
      "channel": "渠道"
    }
  },
  "cost_assumptions": {
    "monthly_rent": 18000.0,
    "monthly_labor": 24000.0,
    "monthly_utilities": 3000.0,
    "monthly_marketing": 2000.0,
    "other_fixed_costs": 3000.0,
    "cash_balance": 120000.0,
    "delivery_commission_rate": 0.2,
    "delivery_packaging_per_order": 1.5
  }
}
```

服务会校验文件归属、文件类型、映射完整性、日期和数值格式、评分范围，以及订单菜品是否存在对应成本记录。成功响应结构与样例经营诊断一致：

- `metrics.survival` 返回实际毛利率、固定成本、月/日保本营业额、保本日订单、月利润投影、距保本线差额、现金支撑期和风险等级。月度结果按照样本日均营业额外推 30 天，属于经营规划估算，不等同于财务报表。
- `metrics.channels` 按订单渠道返回营收、占比、订单数、客单价、食材成本、平台佣金、包材成本、贡献利润和贡献率。名称包含 `delivery`、`外卖`、`美团` 或 `饿了么` 的渠道按外卖计算；其余渠道按堂食/直销计算。渠道贡献利润不分摊房租、人工等固定成本。
- `metrics.time_patterns` 返回早餐、午市、下午、晚市、夜宵和深夜的营收贡献，识别峰值时段，并在至少 6 个有订单营业日时比较样本前后半段趋势；至少 7 个营业日时使用稳健偏差规则标记异常高/低营收日。未出现在 CSV 中的日期不会自动当作零营收。
- `metrics.discounts` 将菜单标价乘以销量后与订单实收比较，区分原价订单和折扣订单，返回让利额、让利率、食材成本、贡献利润和贡献率。未上传活动 ID、优惠券或满减名称时，只能识别发生了让利，不能归因到具体营销活动。
- `metrics._agent` 和顶层 `agent_trace` 返回本次 Agent 的执行模式、模型、Prompt 版本、选择的工具、Planner/Synthesizer 是否使用模型、运行耗时、运行 ID和降级原因。`mode` 可为 `llm`、`hybrid` 或 `deterministic`。该结构是可审计决策摘要，不包含模型原始思维链。
- `metrics._agent_plan` 返回经过后端白名单和输入条件校验后的结构化执行计划。模型不能直接执行 Python 函数、访问数据库或拼接百度 API 请求。

## POST /operating/analyze-sample

使用内置样例 CSV 生成经营诊断报告。

Request:

```json
{
  "project_id": 2,
  "question": "最近营业额下降，问题出在哪里？"
}
```

Response:

```json
{
  "analysis_id": 2,
  "project_id": 2,
  "stage": "operating",
  "intent": "operating_diagnosis",
  "plan": ["analyze_revenue", "analyze_menu_matrix", "analyze_review_topics", "generate_recommendations"],
  "summary": "当前样本期营收 336.0 元，客单价 42.0 元；差评或中评共 2 条。",
  "metrics": {
    "revenue": {
      "total_revenue": 336,
      "order_count": 8,
      "avg_order_value": 42,
      "daily_revenue": []
    },
    "menu": {
      "items": []
    },
    "reviews": {
      "topics": {},
      "review_count": 4,
      "negative_review_count": 2
    }
  },
  "evidence": [],
  "actions": [],
  "warnings": []
}
```

## GET /analysis/{analysis_id}

读取已生成报告。

Response:

```json
{
  "analysis_id": 1,
  "project_id": 1,
  "stage": "pre_open",
  "summary": "当前项目需要重点核验租金、竞品密度和加盟投入是否匹配预估流水。",
  "metrics": {},
  "evidence": [],
  "actions": [],
  "risks": []
}
```

## POST /analysis/{analysis_id}/chat

对已生成的经营报告进行有限 ReAct 追问。

Request：

```json
{
  "question": "外卖贡献率为什么偏低？"
}
```

模型最多执行 3 轮，只能使用 `list_metric_sections`、`read_metric` 和 `read_report_summary` 三个只读工具。回答必须引用有效的 `metrics.*` 路径。模型未配置、调用失败、越权调用工具或引用不存在的指标时返回确定性报告摘要，并在 `fallback_reason` 说明降级原因。
