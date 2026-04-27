# Metrics

Canonical formulas for common KPIs. When a question uses these terms, the
agent should adopt the formula given here verbatim — do not re-derive.

## Revenue

Revenue = `SUM(sales_orders.amount)`. The `amount` column is already the
line total (`quantity * unit_price`); never recompute the multiplication
yourself, and never `SUM(quantity * unit_price)` — round-trip rounding will
disagree with `SUM(amount)`. For "revenue last quarter", filter
`order_date >= date_trunc('quarter', current_date) - interval '3 months'
AND order_date < date_trunc('quarter', current_date)`.

## Average order value (AOV)

AOV = `AVG(sales_orders.amount)`. One row in `sales_orders` is one order
line, so AOV here is per line, not per basket. There is no basket/order
grouping column in this schema; do not invent one.

## Units sold

Units sold = `SUM(sales_orders.quantity)`. This is the volumetric metric;
"top products by units" should rank on this, not on revenue.

## Resolution time

Resolution time = `tickets.resolution_hours` (already computed at seed time
as the diff between `resolved_at` and `created_at`). Use this column
directly for averages and percentiles. It is `NULL` for unresolved tickets,
so include `WHERE resolution_hours IS NOT NULL` in any aggregation, otherwise
Postgres averages will silently exclude them but row counts will not match.

## Resolution SLA

There is no formal SLA column. As a working definition: a ticket meets SLA
when `resolution_hours <=` the priority budget — Low: 72h, Medium: 24h,
High: 8h, Critical: 4h. These are project conventions, not stored in the DB.

## Ticket aging

For unresolved tickets, age = `EXTRACT(EPOCH FROM (now() - created_at)) / 3600`
in hours. Useful for "oldest open tickets" queries. Don't average this with
`resolution_hours` — they measure different populations.

## Ticket volume

Ticket volume = `COUNT(*)` over `tickets`. For trend questions, group by
`date_trunc('day', created_at)` (or `'week'` / `'month'` per the question).
Use `created_at`, not `resolved_at`, for volume — the latter biases toward
historical periods because recent tickets may not be resolved yet.
