# Talk-to-Your-Data GenBI PoC

A natural-language → SQL → chart/table/summary chat over PostgreSQL, built as a Claude Code AI-adoption training deliverable. The terminal CLI ships today (M2); a Streamlit UI lands in M3.

> Full 5-week plan: [PLAN.md](PLAN.md). Project conventions and safety rails: [CLAUDE.md](CLAUDE.md).

## Stack

- **Python 3.12** + **uv** for env/deps
- **PostgreSQL 16** via Docker (host port `5433`)
- **`claude-agent-sdk`** (Python) — agent loop, `@tool`, in-process MCP
- **SQLAlchemy 2** + `psycopg[binary]` + **sqlglot** (SQL safety)
- **Typer** + **Rich** for the CLI; **Streamlit** + **Plotly** land in M3
- **Faker** for synthetic data; **pytest** + **ruff** for dev loop

## Prerequisites

- [Docker](https://www.docker.com/) (for Postgres)
- [uv](https://docs.astral.sh/uv/) (Python env/deps)
- An Anthropic API key

## Setup

```bash
# 1. Clone and install deps
git clone https://github.com/igorkaroza/talk-to-your-data-lab.git
cd talk-to-your-data-lab
uv sync --all-extras

# 2. Configure secrets
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (DATABASE_URL / READONLY_DATABASE_URL defaults are fine)

# 3. Start Postgres and load synthetic data
docker compose up -d postgres
uv run python -m genbi.seed
```

`genbi.seed` provisions two roles — `genbi_admin` (write, used only by the seed script) and `genbi_reader` (SELECT-only, used by everything else) — and populates `sales_orders` (~2000 rows) and `tickets` (~1200 rows) with Faker.

## Run the chat

```bash
uv run python -m genbi.cli chat
```

Example session:

```
you> How many high-priority tickets closed last month?
tool → schema_introspect()
tool → sql_execute   SELECT COUNT(*) FROM tickets WHERE priority = 'High' ...
23 high-priority tickets were closed last month.
```

Type `exit` or Ctrl-D to quit.

## Tests & lint

```bash
uv run pytest -q                          # unit + integration (integration skips if DB down)
uv run ruff format . && uv run ruff check .
```

## Safety rails

Every generated statement is parsed by `sqlglot` and rejected if it isn't a single `SELECT` / `WITH ... SELECT`; `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|TRUNCATE|COPY` are blocked. A `statement_timeout = 5s` is pinned per query and `LIMIT 1000` is appended when absent. The runtime role has no write grants, so any violation of the above would fail at the database anyway. See [CLAUDE.md](CLAUDE.md#safety-rails-non-negotiable) for the non-negotiable list.

## Repo layout

```
src/genbi/        # package: db, seed, safety, tools, agent, cli
tests/            # pytest suite (unit + integration)
app/              # Streamlit UI (M3)
evals/            # regression eval set (M4)
mcp_servers/      # standalone MCPs (M4)
.claude/          # skills, subagents, hooks, settings
.github/workflows # claude-review.yml, eval-regression.yml
docker-compose.yml
```
