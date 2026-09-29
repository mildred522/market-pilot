from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.commerce.contracts import CommerceInteraction, InteractionMode
from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics import ItemLevel, TimeWindow, discover_hot_products


class CommercePlanStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    INSUFFICIENT_DATA = "insufficient_data"


class CommercePlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    priority: Literal["high", "medium", "low"]
    action: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=500)
    success_signal: str = Field(min_length=1, max_length=300)
    evidence: tuple[str, ...] = ()


class CommercePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=2000)
    interaction: CommerceInteraction
    previous_window: TimeWindow
    current_window: TimeWindow
    item_level: ItemLevel = ItemLevel.SKU

    @model_validator(mode="after")
    def require_plan(self) -> "CommercePlanRequest":
        if self.interaction.mode is not InteractionMode.PLAN:
            raise ValueError("commerce plan requests require plan interaction mode")
        return self


class CommercePlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: CommercePlanStatus
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=500)
    steps: tuple[CommercePlanStep, ...] = ()
    evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class CommercePlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int
    project_id: int
    snapshot_id: str
    scope_mode: str
    question: str
    status: CommercePlanStatus
    title: str
    objective: str
    steps: tuple[CommercePlanStep, ...]
    evidence: tuple[str, ...]
    limitations: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None


class CommercePlanService:
    def draft(self, request: CommercePlanRequest, dataset: CommerceDataset) -> CommercePlanDraft:
        candidates = discover_hot_products(
            dataset,
            request.previous_window,
            request.current_window,
            item_level=request.item_level,
        )
        snapshot_ref = f"snapshot:{dataset.snapshot.snapshot_id}"
        if not candidates:
            return CommercePlanDraft(
                status=CommercePlanStatus.INSUFFICIENT_DATA,
                title="暂不生成商品经营计划",
                objective="先补充可比较的商品销售样本，再生成可执行的长期计划。",
                evidence=(snapshot_ref,),
                limitations=(
                    "当前时间窗口没有可用于规划的商品销售记录。",
                    "Plan 只提供建议，不会执行外部业务动作。",
                ),
            )

        steps = tuple(
            _step_for_candidate(candidate, snapshot_ref)
            for candidate in candidates[:6]
        )
        evidence = tuple(
            dict.fromkeys(
                [
                    snapshot_ref,
                    *(evidence for step in steps for evidence in step.evidence),
                ]
            )
        )
        return CommercePlanDraft(
            status=CommercePlanStatus.DRAFT,
            title="商品经营增长与验证计划",
            objective=request.question,
            steps=steps,
            evidence=evidence,
            limitations=(
                "计划基于当前快照和两个时间窗口生成；新数据不会自动改变本计划。",
                "未提供库存、成本、流量和投放能力，相关动作需要人工补充证据。",
                "Plan 只提供建议，不会执行外部业务动作。",
            ),
        )


def _step_for_candidate(candidate: object, snapshot_ref: str) -> CommercePlanStep:
    labels = set(getattr(candidate, "labels", ()))
    item_id = str(getattr(candidate, "item_id"))
    if "emerging_product" in labels:
        return CommercePlanStep(
            priority="high",
            action=f"为商品 {item_id} 设计小规模销售验证，观察连续窗口表现。",
            rationale="当前商品呈现增长信号，但仍需要控制试错规模验证持续性。",
            success_signal="下一窗口销量和成交金额继续增长，且没有明显质量或履约异常。",
            evidence=(snapshot_ref, f"item:{item_id}"),
        )
    if "declining_product" in labels:
        return CommercePlanStep(
            priority="high",
            action=f"复核商品 {item_id} 的定价、详情页和促销变化，先定位下降原因。",
            rationale="当前商品相对上一窗口走弱，现有销售数据不足以直接判断原因。",
            success_signal="下降趋势停止，或经过验证后明确保留、优化或下架决策。",
            evidence=(snapshot_ref, f"item:{item_id}"),
        )
    if "stable_best_seller" in labels:
        return CommercePlanStep(
            priority="medium",
            action=f"围绕商品 {item_id} 做库存、关联销售和复购承接检查。",
            rationale="稳定热销商品适合优先保护供给并验证增量空间。",
            success_signal="商品保持稳定销售，同时关联商品或复购指标出现可观测改善。",
            evidence=(snapshot_ref, f"item:{item_id}"),
        )
    return CommercePlanStep(
        priority="low",
        action=f"补充商品 {item_id} 的销售样本后再决定是否扩大投入。",
        rationale="当前样本量偏小，直接扩大投入容易把偶然波动当作趋势。",
        success_signal="获得更多有效订单后，商品进入稳定、增长或下降分类。",
        evidence=(snapshot_ref, f"item:{item_id}"),
    )
