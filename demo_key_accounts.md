# Key Accounts Playbook

Sales-team definitions for "VIP", "strategic", and "key account". None of
these terms exist as columns in the schema; they must be derived from
`sales_orders` with the rules below. Drag this file onto the GenBI chat
input and the agent will pick the definitions up via `kb_search`.

## VIP customer

A "VIP customer" is a customer in the **top 10 by total revenue**
(`SUM(sales_orders.amount)`) over the **trailing 365 days**. This is a
rolling list — membership changes as new orders land.

When a question uses "VIP", build the list inline and filter:

```sql
WITH vips AS (
  SELECT customer
  FROM sales_orders
  WHERE order_date >= current_date - interval '365 days'
  GROUP BY customer
  ORDER BY SUM(amount) DESC
  LIMIT 10
)
SELECT ...
FROM sales_orders s
JOIN vips USING (customer)
WHERE ...
```

## Strategic account

A "strategic account" is any customer whose **trailing-90-day revenue
exceeds USD 5,000**. Use this when the question phrasing is "strategic"
rather than "VIP" — strategic is broader (size threshold) and VIP is
narrower (top-10 ranking). They overlap but are not the same population.

```sql
WITH strategic AS (
  SELECT customer
  FROM sales_orders
  WHERE order_date >= current_date - interval '90 days'
  GROUP BY customer
  HAVING SUM(amount) > 5000
)
```

## Key account

"Key account" without further qualification means VIP **plus** strategic
combined (`UNION DISTINCT` of the two CTEs above). Sales reviews each key
account quarterly; finance includes both populations on the monthly
revenue-retention slide.

## Churn-at-risk

A VIP or strategic customer is "churn-at-risk" when they have **no orders
in the trailing 30 days** — their most-recent `order_date` is older than
`current_date - interval '30 days'`. Surface these in any retention
question. Customers outside VIP/strategic don't get this label even if
they're inactive; the term is reserved for accounts Sales actively manages.
