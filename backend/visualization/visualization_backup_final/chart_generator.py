from uuid import uuid4
import json
from pathlib import Path


def generate_chart(chart_type, title, data):
    chart_id = str(uuid4())
    path = Path('charts')
    path.mkdir(exist_ok=True)
    file = path / f'{chart_id}.json'
    file.write_text(json.dumps({'type': chart_type,'title':title,'data':data}, default=str))
    return f'/charts/{chart_id}.json'
