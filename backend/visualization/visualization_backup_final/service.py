from .chart_selector import select_chart
from .chart_generator import generate_chart


def create_visualization(question, data):

    chart_type = select_chart(question)

    url = generate_chart(
        chart_type,
        question,
        data
    )

    return {
        "visualization": True,
        "chart_type": chart_type,
        "chart_url": url,
        "title": question,
        "data": data
    }
