from backend.visualization.chart_selector import select_chart


def test_top_performers_uses_bar_chart():
    assert select_chart("top 5 performers")["chart_type"] == "bar"


def test_trend_questions_use_line_chart():
    assert select_chart("headcount trend over time")["chart_type"] == "line"


def test_distribution_questions_use_pie_chart():
    assert select_chart("department distribution")["chart_type"] == "pie"


def test_additional_chart_types_are_supported():
    assert select_chart("employee performance scatter")["chart_type"] == "scatter"
    assert select_chart("department heatmap by region")["chart_type"] == "heatmap"
    assert select_chart("retention benchmark radar")["chart_type"] == "radar"
    assert select_chart("annual salary donut")["chart_type"] == "donut"
    assert select_chart("recruitment pipeline by stage")["chart_type"] == "area"
