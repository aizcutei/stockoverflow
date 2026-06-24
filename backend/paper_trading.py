"""Paper trading engine — virtual account with order management.

Supports:
- Virtual account with configurable initial capital
- Market and limit orders
- Position tracking with P&L
- Trade log
- Performance metrics
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import PaperAccount, PaperPosition, PaperTrade, PendingOrder

logger = logging.getLogger("stockoverflow")


def get_or_create_account(db: Session, name: str = "default", initial_capital: float = 100000.0) -> PaperAccount:
    """Get existing account or create a new one."""
    account = db.execute(
        select(PaperAccount).where(PaperAccount.name == name)
    ).scalar_one_or_none()

    if account is None:
        account = PaperAccount(
            name=name,
            initial_capital=initial_capital,
            cash=initial_capital,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

    return account


def place_order(
    db: Session,
    account_name: str,
    ticker: str,
    side: str,  # "buy" or "sell"
    quantity: int,
    price: float,
    order_type: str = "market",  # "market", "limit", "stop_loss", "take_profit"
    trigger_price: float | None = None,  # for limit/stop orders
    reason: str = "",
) -> dict:
    """Place a paper trade order.

    For limit/stop orders, the order is stored as pending and executed when price conditions are met.
    """
    """Place a paper trade order."""
    account = get_or_create_account(db, account_name)
    ticker = ticker.upper().strip()
    side = side.lower()

    if side not in ("buy", "sell"):
        return {"error": "Side must be 'buy' or 'sell'"}
    if quantity <= 0:
        return {"error": "Quantity must be positive"}
    if price <= 0:
        return {"error": "Price must be positive"}

    # check if selling and have position
    if side == "sell":
        position = db.execute(
            select(PaperPosition).where(
                PaperPosition.account_id == account.id,
                PaperPosition.ticker == ticker,
            )
        ).scalar_one_or_none()
        if position is None or position.quantity < quantity:
            avail = position.quantity if position else 0
            return {"error": f"Insufficient position. Available: {avail}, requested: {quantity}"}

    # check if buying and have enough cash
    if side == "buy":
        total_cost = quantity * price
        if account.cash < total_cost:
            return {"error": f"Insufficient cash. Available: ${account.cash:.2f}, needed: ${total_cost:.2f}"}

    # execute trade
    total = quantity * price
    fee = total * 0.001  # 0.1% fee

    if side == "buy":
        account.cash -= (total + fee)
        # update or create position
        position = db.execute(
            select(PaperPosition).where(
                PaperPosition.account_id == account.id,
                PaperPosition.ticker == ticker,
            )
        ).scalar_one_or_none()

        if position:
            # average cost
            old_total = position.quantity * position.avg_cost
            new_total = old_total + total
            position.quantity += quantity
            position.avg_cost = new_total / position.quantity
        else:
            position = PaperPosition(
                account_id=account.id,
                ticker=ticker,
                quantity=quantity,
                avg_cost=price,
            )
            db.add(position)
    else:  # sell
        account.cash += (total - fee)
        position = db.execute(
            select(PaperPosition).where(
                PaperPosition.account_id == account.id,
                PaperPosition.ticker == ticker,
            )
        ).scalar_one_or_none()

        realized_pnl = (price - position.avg_cost) * quantity
        position.quantity -= quantity
        if position.quantity == 0:
            db.delete(position)

    # record trade
    trade = PaperTrade(
        account_id=account.id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        total=total,
        fee=fee,
        reason=reason,
    )
    db.add(trade)
    db.commit()

    # record in active stocks tracking
    try:
        from backend.market_service import record_trade
        record_trade(db, ticker)
    except Exception:
        pass

    return {
        "trade_id": trade.id,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "total": total,
        "fee": round(fee, 2),
        "cash_remaining": round(account.cash, 2),
        "reason": reason,
    }


def get_account_summary(db: Session, account_name: str = "default", current_prices: dict = None) -> dict:
    """Get account summary with positions and P&L."""
    account = get_or_create_account(db, account_name)
    if current_prices is None:
        current_prices = {}

    positions = db.execute(
        select(PaperPosition).where(PaperPosition.account_id == account.id)
    ).scalars().all()

    pos_list = []
    total_market_value = 0
    total_unrealized = 0

    for p in positions:
        cur_price = current_prices.get(p.ticker, p.avg_cost)
        market_value = p.quantity * cur_price
        unrealized = (cur_price - p.avg_cost) * p.quantity
        unrealized_pct = (cur_price - p.avg_cost) / p.avg_cost * 100 if p.avg_cost > 0 else 0

        total_market_value += market_value
        total_unrealized += unrealized

        pos_list.append({
            "ticker": p.ticker,
            "quantity": p.quantity,
            "avg_cost": round(p.avg_cost, 4),
            "current_price": round(cur_price, 4),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized, 2),
            "unrealized_pct": round(unrealized_pct, 2),
        })

    total_equity = account.cash + total_market_value
    total_return = (total_equity - account.initial_capital) / account.initial_capital * 100

    return {
        "account_name": account.name,
        "initial_capital": account.initial_capital,
        "cash": round(account.cash, 2),
        "market_value": round(total_market_value, 2),
        "total_equity": round(total_equity, 2),
        "total_return_pct": round(total_return, 2),
        "unrealized_pnl": round(total_unrealized, 2),
        "positions": pos_list,
    }


def get_trade_log(db: Session, account_name: str = "default", limit: int = 50) -> list[dict]:
    """Get trade log for an account."""
    account = get_or_create_account(db, account_name)
    trades = db.execute(
        select(PaperTrade)
        .where(PaperTrade.account_id == account.id)
        .order_by(PaperTrade.created_at.desc())
        .limit(limit)
    ).scalars().all()

    return [
        {
            "id": t.id,
            "ticker": t.ticker,
            "side": t.side,
            "quantity": t.quantity,
            "price": round(t.price, 4),
            "total": round(t.total, 2),
            "fee": round(t.fee, 2),
            "reason": t.reason or "",
            "created_at": str(t.created_at),
        }
        for t in trades
    ]


def get_performance_stats(db: Session, account_name: str = "default") -> dict:
    """Calculate performance statistics for paper trading account."""
    account = get_or_create_account(db, account_name)
    all_trades = db.execute(
        select(PaperTrade)
        .where(PaperTrade.account_id == account.id)
        .order_by(PaperTrade.created_at.asc())
    ).scalars().all()

    if not all_trades:
        return {
            "total_trades": 0,
            "buy_trades": 0,
            "sell_trades": 0,
            "total_volume": 0,
            "total_fees": 0,
            "unique_tickers": 0,
            "tickers_traded": [],
            "avg_trade_size": 0,
            "largest_trade": 0,
            "most_traded": None,
            "trade_frequency": {},
        }

    # basic stats
    buy_trades = [t for t in all_trades if t.side == "buy"]
    sell_trades = [t for t in all_trades if t.side == "sell"]
    total_volume = sum(t.total for t in all_trades)
    total_fees = sum(t.fee for t in all_trades)
    tickers = list(set(t.ticker for t in all_trades))

    # most traded ticker
    ticker_counts = {}
    for t in all_trades:
        ticker_counts[t.ticker] = ticker_counts.get(t.ticker, 0) + 1
    most_traded = max(ticker_counts, key=ticker_counts.get) if ticker_counts else None

    # trade frequency by month
    freq = {}
    for t in all_trades:
        month = str(t.created_at)[:7]  # YYYY-MM
        freq[month] = freq.get(month, 0) + 1

    return {
        "total_trades": len(all_trades),
        "buy_trades": len(buy_trades),
        "sell_trades": len(sell_trades),
        "total_volume": round(total_volume, 2),
        "total_fees": round(total_fees, 2),
        "unique_tickers": len(tickers),
        "tickers_traded": tickers,
        "avg_trade_size": round(total_volume / len(all_trades), 2) if all_trades else 0,
        "largest_trade": round(max(t.total for t in all_trades), 2),
        "most_traded": most_traded,
        "trade_frequency": freq,
    }


# ── Pending orders (limit / stop) ────────────────────────────────────


def place_pending_order(
    db: Session,
    account_name: str,
    ticker: str,
    side: str,
    order_type: str,  # "limit", "stop_loss", "take_profit"
    quantity: int,
    trigger_price: float,
    reason: str = "",
) -> dict:
    """Place a pending limit/stop order."""
    account = get_or_create_account(db, account_name)
    ticker = ticker.upper().strip()

    if order_type not in ("limit", "stop_loss", "take_profit"):
        return {"error": "order_type must be limit, stop_loss, or take_profit"}

    order = PendingOrder(
        account_id=account.id,
        ticker=ticker,
        side=side,
        order_type=order_type,
        quantity=quantity,
        trigger_price=trigger_price,
        reason=reason,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "order_id": order.id,
        "ticker": ticker,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "trigger_price": trigger_price,
        "status": "pending",
    }


def get_pending_orders(db: Session, account_name: str = "default") -> list[dict]:
    """Get all pending orders."""
    account = get_or_create_account(db, account_name)
    orders = db.execute(
        select(PendingOrder)
        .where(PendingOrder.account_id == account.id, PendingOrder.status == "pending")
        .order_by(PendingOrder.created_at.desc())
    ).scalars().all()

    return [
        {
            "id": o.id,
            "ticker": o.ticker,
            "side": o.side,
            "order_type": o.order_type,
            "quantity": o.quantity,
            "trigger_price": round(o.trigger_price, 4),
            "reason": o.reason or "",
            "created_at": str(o.created_at),
        }
        for o in orders
    ]


def cancel_pending_order(db: Session, order_id: int, account_name: str = "default") -> dict:
    """Cancel a pending order."""
    account = get_or_create_account(db, account_name)
    order = db.execute(
        select(PendingOrder).where(
            PendingOrder.id == order_id,
            PendingOrder.account_id == account.id,
            PendingOrder.status == "pending",
        )
    ).scalar_one_or_none()

    if order is None:
        return {"error": "Order not found or already processed"}

    order.status = "cancelled"
    db.commit()
    return {"order_id": order_id, "status": "cancelled"}


def get_tax_report(db: Session, account_name: str = "default", year: int = None) -> dict:
    """Generate a tax report of realized capital gains/losses."""
    if year is None:
        year = date.today().year

    account = get_or_create_account(db, account_name)
    trades = db.execute(
        select(PaperTrade)
        .where(PaperTrade.account_id == account.id)
        .where(PaperTrade.side == "sell")
        .order_by(PaperTrade.created_at.asc())
    ).scalars().all()

    # match sells to buys using FIFO
    buy_queue: dict[str, list] = {}  # ticker -> [(price, quantity_remaining)]
    all_buys = db.execute(
        select(PaperTrade)
        .where(PaperTrade.account_id == account.id)
        .where(PaperTrade.side == "buy")
        .order_by(PaperTrade.created_at.asc())
    ).scalars().all()

    for b in all_buys:
        if b.ticker not in buy_queue:
            buy_queue[b.ticker] = []
        buy_queue[b.ticker].append({"price": b.price, "qty": b.quantity, "date": str(b.created_at)[:10]})

    realized_gains = []
    total_gain = 0
    total_loss = 0

    for sell in trades:
        if str(sell.created_at)[:4] != str(year):
            continue

        sell_qty = sell.quantity
        sell_price = sell.price
        sell_date = str(sell.created_at)[:10]

        queue = buy_queue.get(sell.ticker, [])
        while sell_qty > 0 and queue:
            buy = queue[0]
            match_qty = min(sell_qty, buy["qty"])
            gain = (sell_price - buy["price"]) * match_qty

            realized_gains.append({
                "ticker": sell.ticker,
                "buy_date": buy["date"],
                "buy_price": round(buy["price"], 4),
                "sell_date": sell_date,
                "sell_price": round(sell_price, 4),
                "quantity": match_qty,
                "gain_loss": round(gain, 2),
                "type": "short_term" if (datetime.strptime(sell_date, "%Y-%m-%d") - datetime.strptime(buy["date"], "%Y-%m-%d")).days <= 365 else "long_term",
            })

            if gain > 0:
                total_gain += gain
            else:
                total_loss += abs(gain)

            buy["qty"] -= match_qty
            sell_qty -= match_qty
            if buy["qty"] <= 0:
                queue.pop(0)

    return {
        "year": year,
        "total_realized_gain": round(total_gain, 2),
        "total_realized_loss": round(total_loss, 2),
        "net_gain_loss": round(total_gain - total_loss, 2),
        "short_term_gains": round(sum(g["gain_loss"] for g in realized_gains if g["type"] == "short_term"), 2),
        "long_term_gains": round(sum(g["gain_loss"] for g in realized_gains if g["type"] == "long_term"), 2),
        "total_trades": len(realized_gains),
        "trades": realized_gains,
    }


def get_rebalance_suggestion(db: Session, account_name: str = "default", target_alloc: dict = None) -> dict:
    """Suggest portfolio rebalancing based on current positions vs target allocation."""
    account = get_or_create_account(db, account_name)
    positions = db.execute(
        select(PaperPosition).where(PaperPosition.account_id == account.id)
    ).scalars().all()

    if not positions:
        return {"suggestion": "No positions to rebalance", "actions": []}

    total_equity = account.cash
    pos_values = {}
    for p in positions:
        market_value = p.quantity * p.avg_cost  # approximate
        pos_values[p.ticker] = market_value
        total_equity += market_value

    if total_equity <= 0:
        return {"suggestion": "No equity", "actions": []}

    # current allocation
    current_alloc = {t: v / total_equity * 100 for t, v in pos_values.items()}
    cash_pct = account.cash / total_equity * 100

    # if no target, suggest equal weight
    if target_alloc is None:
        n = len(positions)
        target_pct = 100 / (n + 1)  # +1 for cash
        target_alloc = {t: target_pct for t in pos_values}
        target_alloc["CASH"] = target_pct

    actions = []
    for ticker, current_pct in current_alloc.items():
        target_pct = target_alloc.get(ticker, 0)
        diff_pct = current_pct - target_pct
        if abs(diff_pct) > 2:  # only suggest if >2% off
            action = "SELL" if diff_pct > 0 else "BUY"
            amount = abs(diff_pct / 100 * total_equity)
            actions.append({
                "ticker": ticker,
                "action": action,
                "current_pct": round(current_pct, 1),
                "target_pct": round(target_pct, 1),
                "diff_pct": round(diff_pct, 1),
                "amount": round(amount, 2),
            })

    actions.sort(key=lambda x: abs(x["diff_pct"]), reverse=True)

    return {
        "total_equity": round(total_equity, 2),
        "cash_pct": round(cash_pct, 1),
        "current_allocation": {t: round(p, 1) for t, p in current_alloc.items()},
        "target_allocation": {t: round(p, 1) for t, p in target_alloc.items()},
        "actions": actions,
        "needs_rebalance": len(actions) > 0,
    }


def check_pending_orders(db: Session, account_name: str, current_prices: dict[str, float]) -> list[dict]:
    """Check pending orders against current prices and fill if conditions met."""
    account = get_or_create_account(db, account_name)
    orders = db.execute(
        select(PendingOrder).where(
            PendingOrder.account_id == account.id,
            PendingOrder.status == "pending",
        )
    ).scalars().all()

    filled = []
    for order in orders:
        price = current_prices.get(order.ticker)
        if price is None:
            continue

        should_fill = False
        if order.order_type == "limit":
            if order.side == "buy" and price <= order.trigger_price:
                should_fill = True
            elif order.side == "sell" and price >= order.trigger_price:
                should_fill = True
        elif order.order_type == "stop_loss":
            if order.side == "sell" and price <= order.trigger_price:
                should_fill = True
        elif order.order_type == "take_profit":
            if order.side == "sell" and price >= order.trigger_price:
                should_fill = True

        if should_fill:
            result = place_order(
                db, account_name, order.ticker, order.side,
                order.quantity, price, reason=f"Auto-fill {order.order_type}: {order.reason}",
            )
            if not result.get("error"):
                order.status = "filled"
                db.commit()
                filled.append({**result, "order_type": order.order_type, "trigger_price": order.trigger_price})

    return filled
