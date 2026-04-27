# Glossary

Business terms used in user questions, mapped to columns in the GenBI schema.
Each `## H2` section is one retrievable chunk — keep them self-contained.

## Hero product

A "hero product" is one of two SKUs that ship in materially larger quantities
than the rest of the catalog: **Aurora Laptop** (Electronics) and
**Trail Tent** (Outdoor). When a user asks about hero products, filter
`sales_orders.product IN ('Aurora Laptop', 'Trail Tent')`. They reliably
appear near the top of any ranking by `quantity` or `amount`.

## Active customer

There is no `customer_id` or `is_active` flag in this schema. The `customer`
column on `sales_orders` is free-text company name and duplicates across
orders are expected. Treat a customer as "active in the last N days" by
filtering `sales_orders` where `order_date >= current_date - interval 'N days'`
and grouping by `customer`. Anything stricter (lifetime value, retention)
cannot be answered without joining to data this PoC does not have.

## Unresolved ticket

A ticket is unresolved when `tickets.status IN ('Open', 'In Progress')`,
which is equivalent to `tickets.resolved_at IS NULL` and
`tickets.resolution_hours IS NULL`. Anything in `('Resolved', 'Closed')`
counts as resolved and will have a non-null `resolved_at`.

## Region

`sales_orders.region` takes one of: **North, South, East, West, Central**.
North and West together account for the majority of orders by volume;
Central is the smallest by a noticeable margin. Use this column for any
geographic split.

## Category (sales)

`sales_orders.category` takes one of: **Electronics, Home, Outdoor, Apparel**.
Each category has three products. "Category" without further qualification
in a sales question always refers to this column, never to ticket categories.

## Category (tickets)

`tickets.category` is the issue area, distinct from sales categories. Values:
**Network, Auth, Billing, Performance, Data, UI**. If a question mixes
"category" with both sales and tickets context, default to sales unless the
phrasing clearly references tickets/issues.

## Priority

`tickets.priority` takes one of: **Low, Medium, High, Critical**. Low is the
most common (~45% of tickets); Critical is rare (~5%). When a user asks for
"urgent" or "high-priority" tickets, include both **High** and **Critical**.

## Team

`tickets.assigned_team` takes one of: **Platform, AppOps, Data, Security,
Support**. The Support team is the operations escalation queue, distinct
from the engineering teams.
