def select_chart(question: str):
    """Choose a visualization type for HR analytical questions.

    The original tool only supported four static chart types. This expanded
    selector keeps the same API contract but exposes a wider set of valid chart
    styles so the chatbot can render more suitable visualizations when a tool
    call occurs, without changing the surrounding endpoint pipeline.
    """

    q = (question or "").lower()

    if any(x in q for x in [
        "top",
        "best",
        "highest",
        "lowest",
        "performer",
        "ranking",
        "leaderboard",
        "comparison",
        "compare",
        "versus",
        "vs"
    ]):
        return {"chart_type": "bar", "reason": "Ranking comparison"}

    if any(x in q for x in [
        "trend",
        "over time",
        "monthly",
        "yearly",
        "growth",
        "change over",
        "time series",
        "quarterly",
        "historical",
        "by month",
        "by year"
    ]):
        return {"chart_type": "line", "reason": "Time series trend"}

    if any(x in q for x in [
        "distribution",
        "percentage",
        "share",
        "breakdown",
        "composition",
        "mix",
        "segment",
        "department split",
        "by department"
    ]):
        return {"chart_type": "pie", "reason": "Part-to-whole comparison"}

    if any(x in q for x in [
        "correlation",
        "relationship",
        "scatter",
        "dependence",
        "association",
        "relation between"
    ]):
        return {"chart_type": "scatter", "reason": "Relationship analysis"}

    if any(x in q for x in [
        "cumulative",
        "accumulated",
        "stacked",
        "area under",
        "running total",
        "total over time",
        "pipeline",
        "funnel",
        "stage",
        "by stage",
        "journey"
    ]):
        return {"chart_type": "area", "reason": "Cumulative or funnel progression"}

    if any(x in q for x in [
        "survey",
        "score",
        "rating",
        "sentiment",
        "benchmark",
        "performance profile",
        "radar"
    ]):
        return {"chart_type": "radar", "reason": "Multi-metric performance profile"}

    if any(x in q for x in [
        "matrix",
        "heatmap",
        "cross tab",
        "cross-tab",
        "by both",
        "two dimensional",
        "dimension matrix"
    ]):
        return {"chart_type": "heatmap", "reason": "Matrix comparison"}

    if any(x in q for x in [
        "donut",
        "ring",
        "share of total",
        "portion"
    ]):
        return {"chart_type": "donut", "reason": "Donut proportion view"}

    # Keep the legacy table output as a safe fallback for detailed data-heavy
    # output, but prefer a chart in most analytics cases so the UI is not stuck
    # with the old 4-chart limitation.
    return {"chart_type": "bar", "reason": "Analytical comparison"}
