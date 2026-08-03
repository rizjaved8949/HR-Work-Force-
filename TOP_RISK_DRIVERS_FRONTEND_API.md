# Top Attrition Risk Drivers API

## Endpoint

```http
GET /api/v1/dashboard/attrition/top-risk-drivers?limit=3
```

## Purpose

Returns the most frequent model-derived attrition drivers among employees currently predicted as at risk.

## Important wording

Use **Top Attrition Risk Drivers** or **Why Employees Are Flagged at Risk**.
Do not label these values as confirmed exit reasons.

## Main response fields

- `top_driver`: use for the summary card.
- `drivers`: top requested drivers, ordered by mention count.
- `chart_segments`: donut-ready values, including an `Other model risk drivers` segment so the chart totals 100%.
- `share_percent`: share of all model risk-driver mentions.
- `employee_share_percent`: percentage of at-risk employees for whom the driver appeared in their top three.

## Frontend mapping

```javascript
const response = await fetch(
  `${API_BASE_URL}/api/v1/dashboard/attrition/top-risk-drivers?limit=3`
);
const data = await response.json();

const cardTitle = data.top_driver.label;
const cardShare = data.top_driver.share_percent;
const donutData = data.chart_segments;
```
