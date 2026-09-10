from .chart_selector import select_chart


def visualization_tool(question: str, data=None):
    """
    Creates visualization metadata for HR analytical questions.

    Use only when visual analysis is required.
    Returns chart type and chart data.
    """

    if data is None:
        data = []

    decision = select_chart(question)

    return {
        "visualization": True,
        "chart_type": decision["chart_type"],
        "reason": decision["reason"],
        "chart_data": data
    }
