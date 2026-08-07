import math


def calculate_break_even(
    *,
    monthly_rent: float,
    monthly_labor: float,
    monthly_utilities: float,
    monthly_misc: float,
    gross_margin: float,
    avg_order_value: float,
) -> dict[str, float | int]:
    monthly_fixed_cost = monthly_rent + monthly_labor + monthly_utilities + monthly_misc
    daily_fixed_cost = round(monthly_fixed_cost / 30, 2)
    break_even_daily_revenue = round(daily_fixed_cost / gross_margin, 2)
    break_even_daily_orders = math.ceil(break_even_daily_revenue / avg_order_value)

    return {
        "daily_fixed_cost": daily_fixed_cost,
        "break_even_daily_revenue": break_even_daily_revenue,
        "break_even_daily_orders": break_even_daily_orders,
    }
