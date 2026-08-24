from app.agent_runtime.contracts import CorrectionField


CORRECTION_TOOL_DEPENDENCIES: dict[CorrectionField, tuple[str, ...]] = {
    "monthly_rent": ("analyze_survival_line",),
    "monthly_labor": ("analyze_survival_line",),
    "monthly_utilities": ("analyze_survival_line",),
    "monthly_marketing": ("analyze_survival_line",),
    "other_fixed_costs": ("analyze_survival_line",),
    "cash_balance": ("analyze_survival_line",),
    "delivery_commission_rate": ("analyze_channel_profitability",),
    "delivery_packaging_per_order": ("analyze_channel_profitability",),
}
