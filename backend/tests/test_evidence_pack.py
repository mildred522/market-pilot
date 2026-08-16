from app.agent_runtime.evidence_pack import build_evidence_pack


def _metrics() -> dict[str, object]:
    return {
        "revenue": {
            "total_revenue": 336.0,
            "order_count": 8,
            "avg_order_value": 42.0,
        },
        "menu": {
            "items": [
                {
                    "item_name": "招牌拌面",
                    "quantity": 6,
                    "gross_profit": 108.0,
                    "quadrant": "star",
                },
                {
                    "item_name": "酸辣粉",
                    "quantity": 2,
                    "gross_profit": 24.0,
                    "quadrant": "profit",
                },
            ]
        },
        "reviews": {
            "review_count": 4,
            "negative_review_count": 2,
            "topics": {"出餐慢": 1},
        },
        "channels": {
            "delivery_revenue": 112.0,
            "delivery_contribution_margin": 0.367,
        },
        "_targets": {"metrics.revenue.avg_order_value": 45.0},
        "_project_profile": {
            "store_identity": "样例面馆",
            "current_stage": "operating",
            "city": "成都",
            "category": "面馆",
            "preferences": {"report_detail": "concise"},
            "sources": {"city": "user_input"},
        },
        "_agent": {"api_key": "must-not-leak", "prompt": "hidden"},
    }


def _build(**kwargs):
    return build_evidence_pack(
        metrics=_metrics(),
        summary="样本经营诊断",
        evidence=["订单数 8，总营收 336 元"],
        actions=["复盘高峰出餐流程"],
        risks=["当前营收低于保本线"],
        **kwargs,
    )


def test_evidence_pack_exposes_report_facts_with_stable_short_ids():
    first = _build()
    second = _build()
    refs = {fact.canonical_ref for fact in first.facts}

    assert first.pack_id == second.pack_id
    assert [fact.id for fact in first.facts] == [
        f"E{index}" for index in range(1, len(first.facts) + 1)
    ]
    assert "metrics.revenue.total_revenue" in refs
    assert "metrics.menu.items" in refs
    assert "metrics.reviews.topics.出餐慢" in refs
    assert "report.summary" in refs
    assert "report.actions.0" in refs
    assert "targets.metrics.revenue.avg_order_value" in refs
    assert "project_profile.city" in refs
    assert first.fact_for_ref("metrics.revenue.total_revenue").value == 336.0


def test_evidence_pack_never_exposes_internal_agent_metadata():
    payload = _build().model_dump_json()

    assert "must-not-leak" not in payload
    assert '"_agent"' not in payload
    assert '"sources"' not in payload


def test_evidence_pack_compacts_large_arrays_and_marks_the_fact():
    metrics = _metrics()
    metrics["menu"] = {
        "items": [
            {"item_name": f"菜品{index}", "quantity": index, "quadrant": "star"}
            for index in range(10)
        ]
    }

    pack = build_evidence_pack(
        metrics=metrics,
        summary="菜单报告",
        evidence=[],
        actions=[],
        risks=[],
        max_array_items=3,
    )
    fact = pack.fact_for_ref("metrics.menu.items")

    assert len(fact.value) == 3
    assert fact.truncated is True
    assert fact.original_item_count == 10
    assert pack.truncated is True


def test_evidence_pack_respects_the_serialized_fact_budget():
    pack = _build(max_chars=700)

    assert pack.estimated_chars <= 700
    assert pack.truncated is True
    assert pack.omitted_fact_count > 0
