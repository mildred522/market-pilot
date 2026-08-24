from app.agent_runtime.revision import _fallback_revision_plan


def test_fallback_revision_extracts_explicit_rent_correction():
    plan = _fallback_revision_plan("租金不是 18000，应为 2.5 万")

    assert plan.revision_type == "recompute_metrics"
    assert plan.requires_confirmation is True
    assert len(plan.corrections) == 1
    assert plan.corrections[0].field == "monthly_rent"
    assert plan.corrections[0].new_value == 25000


def test_fallback_revision_normalizes_explicit_percentage():
    plan = _fallback_revision_plan("外卖佣金率改成 22%")

    assert plan.corrections[0].field == "delivery_commission_rate"
    assert plan.corrections[0].new_value == 0.22


def test_fallback_revision_does_not_infer_missing_value():
    plan = _fallback_revision_plan("租金写错了，请重新算")

    assert plan.revision_type == "recompute_metrics"
    assert plan.corrections == []
