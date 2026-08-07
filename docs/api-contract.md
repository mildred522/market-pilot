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

上传 CSV 文件。Round 7 中用于保存文件，正式字段映射和导入会在后续扩展。

Form fields:

- `project_id`
- `file_type`
- `file`

Response:

```json
{
  "project_id": 1,
  "file_type": "orders",
  "filename": "orders.csv",
  "storage_path": "storage/uploads/1-orders-orders.csv"
}
```

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

