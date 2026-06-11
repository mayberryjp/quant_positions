"""Position tracking API application.

All data-access functions are injected into create_app() so that tests can
provide fakes without requiring a database connection.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional, Union

from bottle import Bottle, request, response

from quant_positions.api.readiness import (
    ReadinessError,
    ReadinessStatus,
    check_database_readiness,
    sanitize_readiness_error,
)
from quant_positions.domain.models import ALLOWED_EVENT_TYPES

SERVICE_NAME = "quant-positions-api"
log = logging.getLogger(SERVICE_NAME)

# -- type aliases for injectable data functions --
ReadinessCheck = Callable[[], Union[ReadinessStatus, Dict[str, Any]]]
PortfolioList = Callable[[Any], Dict[str, Any]]
PortfolioCreate = Callable[[Any], Dict[str, Any]]
PortfolioDelete = Callable[[int], Optional[Dict[str, Any]]]
PositionList = Callable[[Any], Dict[str, Any]]
PositionDetail = Callable[[int], Optional[Dict[str, Any]]]
PositionByTicker = Callable[[Any], Optional[Dict[str, Any]]]
LedgerImport = Callable[[Any], Dict[str, Any]]
LedgerList = Callable[[Any], Dict[str, Any]]
LedgerDetail = Callable[[int], Optional[Dict[str, Any]]]
LotList = Callable[[Any], Dict[str, Any]]
ReconciliationRunList = Callable[[Any], Dict[str, Any]]
ReconciliationWarningList = Callable[[Any], Dict[str, Any]]

MAX_PAYLOAD_SIZE = 1_000_000  # 1 MB
MAX_TAGS = 20
MAX_TAG_LENGTH = 100
MAX_REASON_LENGTH = 2000
MAX_METADATA_SIZE = 10_000  # 10 KB serialized


# ---------------------------------------------------------------------------
# Query-parameter helpers
# ---------------------------------------------------------------------------

class _ValidationError(Exception):
    pass


def _int_param(raw: str | None, *, default: int, ge: int | None = None, le: int | None = None) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise _ValidationError("invalid integer parameter")
    if ge is not None and value < ge:
        raise _ValidationError(f"value must be >= {ge}")
    if le is not None and value > le:
        raise _ValidationError(f"value must be <= {le}")
    return value


def _bool_param(raw: str | None, *, default: bool | None = None) -> bool | None:
    if raw is None or raw == "":
        return default
    lower = raw.lower()
    if lower in ("true", "1", "yes"):
        return True
    if lower in ("false", "0", "no"):
        return False
    return default


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _status_payload(status: Union[ReadinessStatus, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(status, ReadinessStatus):
        return status.as_json()
    return {"status": "ok", **status}


def _not_found(error: str = "not found") -> dict:
    response.status = 404
    return {"status": "not_found", "error": error}


def _server_error(exc: Exception) -> dict:
    log.exception("handler_error: %s", exc)
    response.status = 500
    return {
        "status": "error",
        "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
    }


def _validation_error_response(detail: str = "validation error") -> dict:
    response.status = 422
    return {"detail": detail}


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    readiness_check: ReadinessCheck = check_database_readiness,
    portfolio_list: PortfolioList | None = None,
    portfolio_create: PortfolioCreate | None = None,
    portfolio_delete: PortfolioDelete | None = None,
    position_list: PositionList | None = None,
    position_detail: PositionDetail | None = None,
    position_by_ticker: PositionByTicker | None = None,
    ledger_import: LedgerImport | None = None,
    ledger_list: LedgerList | None = None,
    ledger_detail: LedgerDetail | None = None,
    lot_list: LotList | None = None,
    reconciliation_run_list: ReconciliationRunList | None = None,
    reconciliation_warning_list: ReconciliationWarningList | None = None,
) -> Bottle:
    api = Bottle()
    api.title = SERVICE_NAME

    # -- request logging hooks --

    @api.hook("before_request")
    def _log_before() -> None:
        request._log_start = time.perf_counter()  # type: ignore[attr-defined]
        log.info(
            "request_start method=%s path=%s query=%s",
            request.method, request.path, request.query_string,
        )

    @api.hook("after_request")
    def _log_after() -> None:
        start = getattr(request, "_log_start", None)
        if start is not None:
            duration_ms = (time.perf_counter() - start) * 1000
            log.info(
                "request_end method=%s path=%s status=%d duration_ms=%.1f",
                request.method, request.path, response.status_code, duration_ms,
            )

    # -- health / readiness (Slice 7) --

    @api.get("/positions/health")
    def health() -> dict:
        return {"status": "ok", "service": SERVICE_NAME}

    @api.get("/positions/ready")
    def ready() -> dict:
        try:
            return _status_payload(readiness_check())
        except Exception as exc:
            response.status = 503
            return {
                "status": "not_ready",
                "database": "error",
                "error": sanitize_readiness_error(exc, os.environ.get("DATABASE_URL")),
            }

    # -- portfolios (Slice 2) --

    @api.get("/portfolios")
    def portfolios_route() -> dict:
        if portfolio_list is None:
            return _server_error(RuntimeError("portfolio_list not configured"))
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=200)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()

        from quant_positions.repository.portfolios import PortfolioListParams
        enabled = _bool_param(request.query.get("enabled"))
        params = PortfolioListParams(enabled=enabled, limit=limit, offset=offset)
        try:
            return portfolio_list(params)
        except Exception as exc:
            return _server_error(exc)

    @api.post("/portfolios")
    def create_portfolio_route() -> dict:
        if portfolio_create is None:
            return _server_error(RuntimeError("portfolio_create not configured"))
        try:
            body = request.json
        except Exception:
            return _validation_error_response("invalid JSON body")
        if body is None or not isinstance(body, dict):
            return _validation_error_response("request body required")

        name = body.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            return _validation_error_response("name is required")

        portfolio_type = body.get("portfolio_type", "paper")
        if portfolio_type not in ("paper", "manual", "tracked"):
            return _validation_error_response("portfolio_type must be paper, manual, or tracked")

        currency = body.get("currency", "USD")
        enabled = body.get("enabled", True)
        metadata = body.get("metadata", {})

        if metadata and len(json.dumps(metadata)) > MAX_METADATA_SIZE:
            return _validation_error_response("metadata too large")

        from quant_positions.repository.portfolios import CreatePortfolioParams
        params = CreatePortfolioParams(
            name=name.strip(),
            portfolio_type=portfolio_type,
            currency=currency,
            enabled=enabled,
            metadata=metadata,
        )
        try:
            result = portfolio_create(params)
            response.status = 201
            return result
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                response.status = 409
                return {"status": "conflict", "error": f"portfolio '{name}' already exists"}
            return _server_error(exc)

    @api.delete("/portfolios/<portfolio_id>")
    def delete_portfolio_route(portfolio_id: str) -> dict:
        if portfolio_delete is None:
            return _server_error(RuntimeError("portfolio_delete not configured"))
        try:
            pid = int(portfolio_id)
        except (ValueError, TypeError):
            return _validation_error_response("portfolio_id must be an integer")
        try:
            result = portfolio_delete(pid)
        except Exception as exc:
            if "in use" in str(exc).lower() or "has positions" in str(exc).lower():
                response.status = 409
                return {"status": "conflict", "error": str(exc)}
            return _server_error(exc)
        if result is None:
            return _not_found("portfolio not found")
        return result

    # -- positions (Slice 2) --

    @api.get("/positions")
    def positions_route() -> dict:
        if position_list is None:
            return _server_error(RuntimeError("position_list not configured"))
        try:
            limit = _int_param(request.query.get("limit"), default=100, ge=1, le=500)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()

        from quant_positions.repository.positions import PositionListParams
        portfolio = request.query.get("portfolio") or None
        status = request.query.get("status") or None
        ticker = request.query.get("ticker") or None
        market = request.query.get("market") or None
        locale = request.query.get("locale") or None

        params = PositionListParams(
            portfolio=portfolio, status=status, ticker=ticker,
            market=market, locale=locale, limit=limit, offset=offset,
        )
        try:
            return position_list(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/positions/by-ticker/<ticker>")
    def position_by_ticker_route(ticker: str) -> dict:
        if position_by_ticker is None:
            return _server_error(RuntimeError("position_by_ticker not configured"))

        portfolio = request.query.get("portfolio")
        if not portfolio:
            return _validation_error_response("portfolio query parameter is required")

        from quant_positions.repository.positions import PositionTickerLookupParams
        params = PositionTickerLookupParams(
            portfolio=portfolio,
            ticker=ticker,
            market=request.query.get("market", "stocks"),
            locale=request.query.get("locale", "us"),
        )
        try:
            result = position_by_ticker(params)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("position not found")
        return result

    @api.get("/positions/<position_id>")
    def position_detail_route(position_id: str) -> dict:
        if position_detail is None:
            return _server_error(RuntimeError("position_detail not configured"))
        try:
            pid = int(position_id)
        except (ValueError, TypeError):
            return _validation_error_response("position_id must be an integer")
        try:
            result = position_detail(pid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("position not found")
        return result

    # -- ledger import (Slice 3) --

    @api.post("/position-ledger/import")
    def ledger_import_route() -> dict:
        if ledger_import is None:
            return _server_error(RuntimeError("ledger_import not configured"))
        try:
            body = request.json
        except Exception:
            return _validation_error_response("invalid JSON body")
        if body is None or not isinstance(body, dict):
            return _validation_error_response("request body required")

        # Validate required fields
        errors = _validate_ledger_import_body(body)
        if errors:
            return _validation_error_response("; ".join(errors))

        # Parse and build params
        try:
            quantity_delta = Decimal(str(body["quantity_delta"]))
        except (InvalidOperation, ValueError, TypeError):
            return _validation_error_response("invalid quantity_delta")

        price = None
        if body.get("price") is not None:
            try:
                price = Decimal(str(body["price"]))
                if price < 0:
                    return _validation_error_response("price must be >= 0")
            except (InvalidOperation, ValueError, TypeError):
                return _validation_error_response("invalid price")

        fees = Decimal("0")
        if body.get("fees") is not None:
            try:
                fees = Decimal(str(body["fees"]))
                if fees < 0:
                    return _validation_error_response("fees must be >= 0")
            except (InvalidOperation, ValueError, TypeError):
                return _validation_error_response("invalid fees")

        try:
            occurred_at = datetime.fromisoformat(body["occurred_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return _validation_error_response("invalid occurred_at timestamp")

        tags = body.get("tags", [])
        if not isinstance(tags, list):
            return _validation_error_response("tags must be a list")
        if len(tags) > MAX_TAGS:
            return _validation_error_response(f"maximum {MAX_TAGS} tags allowed")
        for tag in tags:
            if not isinstance(tag, str) or len(tag) > MAX_TAG_LENGTH:
                return _validation_error_response(f"each tag must be a string <= {MAX_TAG_LENGTH} chars")

        metadata = body.get("metadata", {})
        if metadata and len(json.dumps(metadata)) > MAX_METADATA_SIZE:
            return _validation_error_response("metadata too large")

        from quant_positions.repository.ledger import LedgerImportParams
        params = LedgerImportParams(
            portfolio=body["portfolio"],
            idempotency_key=body["idempotency_key"],
            source=body["source"],
            ticker=body["ticker"],
            market=body.get("market", "stocks"),
            locale=body.get("locale", "us"),
            event_type=body["event_type"],
            quantity_delta=quantity_delta,
            occurred_at=occurred_at,
            reason=body["reason"],
            source_event_id=body.get("source_event_id"),
            price=price,
            fees=fees,
            tags=tags,
            metadata=metadata,
        )

        try:
            result = ledger_import(params)
        except Exception as exc:
            return _server_error(exc)

        if result.get("status") == "rejected":
            response.status = 422
        elif result.get("status") == "duplicate":
            response.status = 200
        elif result.get("status") == "recorded":
            response.status = 201

        return result

    # -- ledger read (Slice 6) --

    @api.get("/position-ledger")
    def ledger_list_route() -> dict:
        if ledger_list is None:
            return _server_error(RuntimeError("ledger_list not configured"))
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=200)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()

        from quant_positions.repository.ledger import LedgerListParams
        params = LedgerListParams(
            portfolio=request.query.get("portfolio") or None,
            ticker=request.query.get("ticker") or None,
            symbol_id=int(request.query.get("symbol_id")) if request.query.get("symbol_id") else None,
            event_type=request.query.get("event_type") or None,
            source=request.query.get("source") or None,
            from_date=request.query.get("from_date") or None,
            to_date=request.query.get("to_date") or None,
            limit=limit,
            offset=offset,
        )
        try:
            return ledger_list(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/position-ledger/<ledger_entry_id>")
    def ledger_detail_route(ledger_entry_id: str) -> dict:
        if ledger_detail is None:
            return _server_error(RuntimeError("ledger_detail not configured"))
        try:
            lid = int(ledger_entry_id)
        except (ValueError, TypeError):
            return _validation_error_response("ledger_entry_id must be an integer")
        try:
            result = ledger_detail(lid)
        except Exception as exc:
            return _server_error(exc)
        if result is None:
            return _not_found("ledger entry not found")
        return result

    # -- lots (Slice 6) --

    @api.get("/position-lots")
    def lots_route() -> dict:
        if lot_list is None:
            return _server_error(RuntimeError("lot_list not configured"))
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=200)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()

        from quant_positions.repository.lots import LotListParams
        params = LotListParams(
            portfolio=request.query.get("portfolio") or None,
            ticker=request.query.get("ticker") or None,
            status=request.query.get("status") or None,
            limit=limit,
            offset=offset,
        )
        try:
            return lot_list(params)
        except Exception as exc:
            return _server_error(exc)

    # -- reconciliation (Slice 6 & 7) --

    @api.get("/reconciliation/runs")
    def reconciliation_runs_route() -> dict:
        if reconciliation_run_list is None:
            return _server_error(RuntimeError("reconciliation_run_list not configured"))
        try:
            limit = _int_param(request.query.get("limit"), default=20, ge=1, le=100)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()

        from quant_positions.repository.reconciliation import ReconciliationRunListParams
        params = ReconciliationRunListParams(
            status=request.query.get("status") or None,
            limit=limit,
            offset=offset,
        )
        try:
            return reconciliation_run_list(params)
        except Exception as exc:
            return _server_error(exc)

    @api.get("/reconciliation/warnings")
    def reconciliation_warnings_route() -> dict:
        if reconciliation_warning_list is None:
            return _server_error(RuntimeError("reconciliation_warning_list not configured"))
        try:
            limit = _int_param(request.query.get("limit"), default=50, ge=1, le=200)
            offset = _int_param(request.query.get("offset"), default=0, ge=0)
        except _ValidationError:
            return _validation_error_response()

        from quant_positions.repository.reconciliation import ReconciliationWarningListParams
        run_id = request.query.get("run_id")
        portfolio_id = request.query.get("portfolio_id")
        params = ReconciliationWarningListParams(
            run_id=int(run_id) if run_id else None,
            portfolio_id=int(portfolio_id) if portfolio_id else None,
            limit=limit,
            offset=offset,
        )
        try:
            return reconciliation_warning_list(params)
        except Exception as exc:
            return _server_error(exc)

    return api


def _validate_ledger_import_body(body: dict) -> list[str]:
    """Validate required fields for ledger import. Returns list of error strings."""
    errors: list[str] = []
    required = ("portfolio", "idempotency_key", "ticker", "event_type", "source", "occurred_at", "reason")
    for field in required:
        val = body.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"{field} is required")

    if body.get("event_type") and body["event_type"] not in ALLOWED_EVENT_TYPES:
        errors.append(f"unsupported event_type: {body['event_type']}")

    if body.get("reason") and len(body["reason"]) > MAX_REASON_LENGTH:
        errors.append(f"reason must be <= {MAX_REASON_LENGTH} characters")

    if "quantity_delta" not in body:
        errors.append("quantity_delta is required")

    return errors


# ---------------------------------------------------------------------------
# Module-level setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
    force=True,
)

print(
    f"[{SERVICE_NAME}] module={__file__} python={sys.executable} "
    f"version={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    file=sys.stderr,
    flush=True,
)


def _default_app() -> Bottle:
    """Create the app with real repository functions wired in."""
    from quant_positions.repository.portfolios import list_portfolios, create_portfolio
    from quant_positions.repository.positions import (
        list_positions, get_position_by_id, get_position_by_ticker,
    )
    from quant_positions.repository.ledger import (
        import_ledger_entry, list_ledger_entries, get_ledger_entry_by_id,
    )
    from quant_positions.repository.lots import list_lots
    from quant_positions.repository.reconciliation import (
        list_reconciliation_runs, list_reconciliation_warnings,
    )

    return create_app(
        portfolio_list=list_portfolios,
        portfolio_create=create_portfolio,
        position_list=list_positions,
        position_detail=get_position_by_id,
        position_by_ticker=get_position_by_ticker,
        ledger_import=import_ledger_entry,
        ledger_list=list_ledger_entries,
        ledger_detail=get_ledger_entry_by_id,
        lot_list=list_lots,
        reconciliation_run_list=list_reconciliation_runs,
        reconciliation_warning_list=list_reconciliation_warnings,
    )


app = _default_app()


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("API_LISTEN_ADDRESS", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8001"))
    log.info("Starting positions API server on %s:%d...", host, port)
    serve(app, host=host, port=port, threads=20)
