"""Position accounting rules.

Accounting Method: Weighted Average Cost
=========================================

When a positive-quantity event occurs (buy / opening balance / transfer in):
    new_total_cost = (old_quantity * old_avg_cost) + (abs(quantity_delta) * price)
    new_quantity   = old_quantity + abs(quantity_delta)
    new_avg_cost   = new_total_cost / new_quantity   (if new_quantity > 0)

When a negative-quantity event occurs (sell / transfer out):
    realized_pnl  += abs(quantity_delta) * (price - old_avg_cost)   [if price given]
    new_quantity   = old_quantity - abs(quantity_delta)
    avg_cost stays the same (weighted average does not change on sell)

Fees are subtracted from realized PnL.

Known Limitations
-----------------
- Lot-level realized PnL uses FIFO selection as documented default.
- Complex lot-selection methods (specific-id, LIFO, tax-optimal) are deferred.
- If no price is provided on a sell, realized PnL is not updated for that event.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass
class PositionUpdate:
    """Result of applying a ledger event to a position."""
    new_quantity: Decimal
    new_average_cost: Decimal
    realized_pnl_delta: Decimal
    fees: Decimal


def apply_ledger_event(
    current_quantity: Decimal,
    current_avg_cost: Decimal,
    quantity_delta: Decimal,
    price: Decimal | None,
    fees: Decimal,
) -> PositionUpdate:
    """Apply a single ledger event to current position state.

    Returns the new position state after the event.
    """
    if quantity_delta > 0:
        return _apply_increase(current_quantity, current_avg_cost, quantity_delta, price, fees)
    elif quantity_delta < 0:
        return _apply_decrease(current_quantity, current_avg_cost, quantity_delta, price, fees)
    else:
        # Zero-delta events (e.g. fee-only)
        return PositionUpdate(
            new_quantity=current_quantity,
            new_average_cost=current_avg_cost,
            realized_pnl_delta=-fees,
            fees=fees,
        )


def _apply_increase(
    current_quantity: Decimal,
    current_avg_cost: Decimal,
    quantity_delta: Decimal,
    price: Decimal | None,
    fees: Decimal,
) -> PositionUpdate:
    event_price = price if price is not None else Decimal("0")
    old_total_cost = current_quantity * current_avg_cost
    new_cost = abs(quantity_delta) * event_price
    new_quantity = current_quantity + quantity_delta

    if new_quantity > 0:
        new_avg_cost = ((old_total_cost + new_cost) / new_quantity).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )
    else:
        new_avg_cost = Decimal("0")

    return PositionUpdate(
        new_quantity=new_quantity,
        new_average_cost=new_avg_cost,
        realized_pnl_delta=-fees,
        fees=fees,
    )


def _apply_decrease(
    current_quantity: Decimal,
    current_avg_cost: Decimal,
    quantity_delta: Decimal,
    price: Decimal | None,
    fees: Decimal,
) -> PositionUpdate:
    abs_delta = abs(quantity_delta)
    new_quantity = current_quantity + quantity_delta  # quantity_delta is negative

    realized_pnl_delta = Decimal("0")
    if price is not None:
        realized_pnl_delta = abs_delta * (price - current_avg_cost)
    realized_pnl_delta -= fees

    # Average cost does not change on sell (weighted average method)
    new_avg_cost = current_avg_cost if new_quantity > 0 else Decimal("0")

    return PositionUpdate(
        new_quantity=new_quantity,
        new_average_cost=new_avg_cost,
        realized_pnl_delta=realized_pnl_delta,
        fees=fees,
    )
