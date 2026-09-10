def select_chart(question: str):

    q = question.lower()


    if any(x in q for x in [
        "top",
        "best",
        "highest",
        "lowest",
        "performer",
        "ranking"
    ]):
        return {
            "chart_type":"bar",
            "reason":"Ranking comparison"
        }


    if any(x in q for x in [
        "trend",
        "over time",
        "monthly",
        "yearly",
        "growth"
    ]):
        return {
            "chart_type":"line",
            "reason":"Time series trend"
        }


    if any(x in q for x in [
        "distribution",
        "percentage",
        "share",
        "breakdown"
    ]):
        return {
            "chart_type":"pie",
            "reason":"Part to whole comparison"
        }


    return {
        "chart_type":"table",
        "reason":"Detailed data view"
    }
