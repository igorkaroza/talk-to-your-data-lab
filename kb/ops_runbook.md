# Ops runbook

Tribal knowledge that affects how to interpret the data — caveats, known
biases, and stories worth surfacing in summaries.

## Support team is slower

The Support team's average `resolution_hours` is roughly **60% higher** than
the engineering teams (Platform, AppOps, Data, Security). This is by design
of the synthetic data — Support is the escalation queue and handles
multi-touch tickets. When a "team performance" question surfaces this gap,
call it out as expected, not as a regression.

## Hero products dominate volume

Aurora Laptop and Trail Tent ship in larger quantities than other SKUs (up
to 6 units per line vs. up to 3 for the rest). They will reliably appear at
the top of any `ORDER BY SUM(quantity)` or `ORDER BY SUM(amount)` ranking.
If a user is surprised they're at the top, that's the explanation.

## Region skew

Volume is intentionally uneven across regions. Approximate weights:
North 28%, West 26%, East 22%, South 14%, Central 10%. A "regional
breakdown" chart will look lopsided — that's the dataset, not a bug.

## Unresolved ticket nuances

Roughly 80% of tickets are resolved. The unresolved 20% are split between
"Open" and "In Progress" status. They have `resolution_hours IS NULL`. If a
question asks for "average resolution time", filter to resolved tickets —
otherwise the result is silently biased.

## Date ranges in the synthetic data

The seed script generates:
- `sales_orders.order_date` over the **last 365 days** (relative to seed time).
- `tickets.created_at` over the **last 180 days**.

Questions like "show me 2019 sales" will return zero rows. Surface the date
range in the answer when a user asks for a period the data does not cover.

## Currency

All monetary amounts are unitless numbers in the synthetic data; we treat
them as USD by convention. Do not wrap totals in `$…$` Markdown — that
parses as LaTeX in the Streamlit UI. Use `USD 12,345` or escape the dollar
sign (`\$12,345`).
