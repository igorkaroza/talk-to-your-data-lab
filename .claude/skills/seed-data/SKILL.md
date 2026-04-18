---
name: seed-data
description: Wipe and reseed the local Postgres with fresh synthetic sales_orders and tickets data. Also provisions the read-only genbi_reader role. Run after schema changes or before demos.
allowed-tools: Bash(docker compose:*), Bash(uv run:*), Bash(docker ps:*)
---

# /seed-data

Regenerate the PoC database state.

1. Confirm Postgres is running: `docker compose ps postgres`. If it isn't up, start it with `docker compose up -d postgres` and wait ~3s for the healthcheck.
2. Run the seed: `uv run python -m genbi.seed`.
3. Report back the row counts it printed (e.g. `2000 sales_orders, 1200 tickets`) and confirm the `genbi_reader` role was provisioned.

**What it does** (see [src/genbi/seed.py](src/genbi/seed.py)):
- Drops + recreates `sales_orders` and `tickets`.
- Inserts ~2k sales rows and ~1.2k tickets via Faker. Data is deterministic (`seed=42`) and biased toward demo stories — regional skew, a couple of hero products, a slower "Support" team.
- (Re)creates `genbi_reader` with `USAGE` on `public` + `SELECT` on tables only.

**Do not** invoke `genbi.seed` against any DB the user hasn't explicitly designated as the dev Postgres — it's destructive (drops tables).

If the seed fails with a connection error, check `.env` is populated (copy from `.env.example`) and that host port 5433 is free.
