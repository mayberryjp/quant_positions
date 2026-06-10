# quant_positions

Database-backed position tracking and accounting service for the quant momentum
pipeline.

## Local Infrastructure

Requirements:

- Docker with Docker Compose v2
- Python 3.12

Bootstrap:

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate    # or .venv\Scripts\Activate.ps1 on Windows
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
docker compose up -d postgres
docker compose ps
alembic upgrade head
```

Stop local services without deleting data:

```bash
docker compose stop postgres
```

Reset local database state:

```bash
docker compose down -v
```

## Running Tests

```bash
python3 -m pytest -q
```

Tests use fake/injected dependencies and do not require a running database.

## Container Image

Build:

```bash
docker build -t quant-positions:dev .
```

Run:

```bash
docker run --rm quant-positions:dev python3 -m pytest -q
```

The container runs `supervisord` by default, which starts both the API server
and the reconciliation worker.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/positions/health` | Liveness check (no DB required) |
| GET | `/positions/ready` | Readiness check (DB + schema + worker heartbeats) |
| GET | `/portfolios` | List portfolios |
| POST | `/portfolios` | Create a portfolio |
| GET | `/positions` | List positions (filterable) |
| GET | `/positions/{position_id}` | Position detail |
| GET | `/positions/by-ticker/{ticker}` | Position lookup by ticker + portfolio |
| POST | `/position-ledger/import` | Import a position-changing event |
| GET | `/position-ledger` | List ledger entries (filterable) |
| GET | `/position-ledger/{ledger_entry_id}` | Ledger entry detail |
| GET | `/position-lots` | List position lots (filterable) |
| GET | `/reconciliation/runs` | List reconciliation runs |
| GET | `/reconciliation/warnings` | List reconciliation warnings |

## API Examples

### Create a Portfolio

```bash
curl -X POST http://localhost:8001/portfolios \
  -H "Content-Type: application/json" \
  -d '{"name": "paper-main", "portfolio_type": "paper", "currency": "USD"}'
```

Response:

```json
{
  "id": 1,
  "name": "paper-main",
  "portfolio_type": "paper",
  "currency": "USD",
  "enabled": true,
  "metadata": {},
  "created_at": "2026-06-10T12:00:00+00:00",
  "updated_at": "2026-06-10T12:00:00+00:00"
}
```

### Import a Ledger Entry (External Position Change)

```bash
curl -X POST http://localhost:8001/position-ledger/import \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio": "paper-main",
    "idempotency_key": "paper-main:external-system:AAPL:event-001",
    "source": "external-position-event",
    "source_event_id": "event-001",
    "ticker": "AAPL",
    "market": "stocks",
    "locale": "us",
    "event_type": "external_position_change",
    "quantity_delta": 10,
    "price": 185.50,
    "fees": 1.25,
    "occurred_at": "2026-06-09T15:31:00Z",
    "reason": "Imported from external position source",
    "tags": ["imported"],
    "metadata": {"external_system": "example"}
  }'
```

Response:

```json
{
  "status": "recorded",
  "ledger_entry_id": 123,
  "portfolio": "paper-main",
  "submitted_ticker": "AAPL",
  "symbol_id": null,
  "position_id": 45,
  "quantity_delta": "10"
}
```

### Import a Ledger Entry (Manual Adjustment)

```bash
curl -X POST http://localhost:8001/position-ledger/import \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio": "paper-main",
    "idempotency_key": "paper-main:manual:AAPL:adjustment-001",
    "source": "operator",
    "ticker": "AAPL",
    "market": "stocks",
    "locale": "us",
    "event_type": "manual_adjustment",
    "quantity_delta": -2,
    "occurred_at": "2026-06-09T16:00:00Z",
    "reason": "Manual correction after position review"
  }'
```

### Lookup Position by Ticker

```bash
curl "http://localhost:8001/positions/by-ticker/AAPL?portfolio=paper-main"
```

### List Ledger Entries with Filters

```bash
curl "http://localhost:8001/position-ledger?portfolio=paper-main&ticker=AAPL&event_type=manual_adjustment&limit=10"
```

### Check Reconciliation Warnings

```bash
curl "http://localhost:8001/reconciliation/warnings"
```

## Position Accounting

### Method: Weighted Average Cost

**Buy (positive quantity_delta):**

- `new_total_cost = (old_quantity × old_avg_cost) + (quantity_delta × price)`
- `new_avg_cost = new_total_cost / new_quantity`

**Sell (negative quantity_delta):**

- `realized_pnl = abs(quantity_delta) × (price - avg_cost)`
- Average cost does not change on sell
- If no price is provided on sell, realized PnL is not updated

**Fees** are subtracted from realized PnL.

### Known Limitations

- Lot-level realized PnL uses FIFO selection as the documented default
- Complex lot-selection methods (specific-id, LIFO, tax-optimal) are deferred
- Tax accounting is out of scope
- Real-time market data valuation is out of scope

## Idempotency Rules

Every ledger import requires a unique `idempotency_key`. If a duplicate key is
submitted:

- The original entry is returned with `"status": "duplicate"`
- No position update occurs
- HTTP status code is 200 (not 201)

Recommended key format: `{portfolio}:{source}:{ticker}:{event-id}`

## Allowed Ledger Event Types

| Event Type | Description |
|------------|-------------|
| `external_position_change` | Position change from an external system |
| `manual_adjustment` | Operator-initiated correction |
| `transfer_in` | Shares transferred into the portfolio |
| `transfer_out` | Shares transferred out of the portfolio |
| `stock_split` | Stock split adjustment |
| `fee` | Fee-only event (no quantity change) |
| `correction` | Error correction |
| `opening_balance` | Initial position import |

## Validation Bounds

- `price` must be >= 0 (if provided)
- `fees` must be >= 0
- `tags` must be a list of strings, max 20 tags, each max 100 chars
- `metadata` JSON must be <= 10 KB serialized
- `reason` must be <= 2000 characters
- `portfolio_type` must be one of: `paper`, `manual`, `tracked`

## Reconciliation Worker

The reconciliation worker runs continuously under supervisor. It:

1. Updates its heartbeat in `worker_heartbeats`
2. Creates a `reconciliation_runs` record
3. For each current position, derives expected quantity from ledger entry sum
4. Records mismatches as `reconciliation_warnings`
5. Detects orphaned ledger entries (referencing deleted positions)

### Local Testing (Single Pass)

```bash
python -m quant_positions.workers.reconciliation --once
```

### Container Run (Continuous)

```bash
python -m quant_positions.workers.reconciliation --schedule 300
```

## External Integration Boundary

This service is strictly responsible for position tracking. It does not own:

- Upstream account workflows
- Trading workflows
- External system state
- Broker connectivity

Other systems may publish/import position-changing events through the
`POST /position-ledger/import` endpoint. This keeps position tracking and
accounting stable while allowing trading systems, broker adapters, and account
importers to evolve in separate codebases.

## Database Schema

Schema: `position_tracking`

| Table | Purpose |
|-------|---------|
| `portfolios` | Logical account/portfolio containers |
| `positions` | Current aggregate position state |
| `position_lots` | Cost-basis records for lot tracking |
| `position_ledger_entries` | Immutable, append-only accounting events |
| `position_snapshots` | Point-in-time position state for reconciliation |
| `reconciliation_runs` | Reconciliation execution records |
| `reconciliation_warnings` | Detected mismatches |
| `worker_heartbeats` | Worker liveness visibility |

Migration: `alembic upgrade head`
