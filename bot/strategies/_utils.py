"""
NIJA Strategies – shared utilities
====================================

Small helpers shared across all strategy modules.
"""


def _last(series):
    """
    Return the last scalar value from a pandas Series or a plain number.

    Args:
        series: pandas Series, scalar, or None.

    Returns:
        float | None
    """
    if series is None:
        return None
    if hasattr(series, "iloc"):
        if series.empty:
            return None
        return float(series.iloc[-1])
    try:
        return float(series)
    except (TypeError, ValueError):
        return None
