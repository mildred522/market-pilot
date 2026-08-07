import pandas as pd


def validate_required_columns(
    frame: pd.DataFrame, required_columns: set[str]
) -> list[str]:
    return sorted(required_columns - set(frame.columns))
