"""Conversation service — multi-turn LLM chat with persistence."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Conversation, LLMHistory

logger = logging.getLogger("stockoverflow")


def get_history(db: Session, ticker: str, limit: int = 20) -> list[dict]:
    """Get conversation history for a ticker, most recent first."""
    stmt = (
        select(Conversation)
        .where(Conversation.ticker == ticker.upper())
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "role": r.role,
            "content": r.content,
            "model": r.model,
            "created_at": str(r.created_at),
        }
        for r in reversed(rows)
    ]


def save_message(db: Session, ticker: str, role: str, content: str, model: str = None) -> None:
    """Save a single message to conversation history."""
    db.add(Conversation(
        ticker=ticker.upper(),
        role=role,
        content=content,
        model=model,
    ))
    db.commit()


def save_prediction(db: Session, ticker: str, result: dict) -> None:
    """Save an LLM prediction result to history."""
    if result.get("error"):
        return
    db.add(LLMHistory(
        ticker=ticker.upper(),
        action=result.get("action"),
        buy_price=result.get("buy_price"),
        sell_price=result.get("sell_price"),
        stop_loss=result.get("stop_loss"),
        take_profit=result.get("take_profit"),
        confidence=result.get("confidence"),
        reasoning=result.get("reasoning"),
        model=result.get("model"),
    ))
    db.commit()


def get_prediction_history(db: Session, ticker: str, limit: int = 10) -> list[dict]:
    """Get prediction history for a ticker."""
    stmt = (
        select(LLMHistory)
        .where(LLMHistory.ticker == ticker.upper())
        .order_by(LLMHistory.created_at.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "action": r.action,
            "buy_price": r.buy_price,
            "sell_price": r.sell_price,
            "stop_loss": r.stop_loss,
            "take_profit": r.take_profit,
            "confidence": r.confidence,
            "reasoning": r.reasoning,
            "model": r.model,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]


def calibrate_confidence(db: Session, ticker: str, candles: list[dict]) -> dict:
    """Calibrate confidence based on historical prediction accuracy."""
    from sqlalchemy import func as sa_func

    # get all past predictions for this ticker
    preds = db.execute(
        select(LLMHistory)
        .where(LLMHistory.ticker == ticker.upper())
        .order_by(LLMHistory.created_at.asc())
    ).scalars().all()

    if len(preds) < 3:
        return {
            "calibrated": False,
            "reason": f"Need at least 3 predictions, have {len(preds)}",
            "raw_confidence": None,
            "adjusted_confidence": None,
        }

    # build price lookup by date
    price_by_date = {}
    for c in candles:
        price_by_date[str(c["date"])] = c["close"]

    # evaluate each prediction
    correct = 0
    total = 0
    confidence_scores = []
    actual_outcomes = []

    for pred in preds:
        pred_date = str(pred.created_at)[:10]
        # find next trading day price
        dates = sorted(price_by_date.keys())
        pred_idx = None
        for i, d in enumerate(dates):
            if d >= pred_date:
                pred_idx = i
                break

        if pred_idx is None or pred_idx + 1 >= len(dates):
            continue

        entry_price = price_by_date[dates[pred_idx]]
        next_price = price_by_date[dates[pred_idx + 1]]
        actual_return = (next_price - entry_price) / entry_price

        was_correct = False
        if pred.action == "BUY" and actual_return > 0:
            was_correct = True
        elif pred.action == "SELL" and actual_return < 0:
            was_correct = True
        elif pred.action == "HOLD" and abs(actual_return) < 0.01:
            was_correct = True

        if was_correct:
            correct += 1
        total += 1
        confidence_scores.append(pred.confidence or 50)
        actual_outcomes.append(was_correct)

    if total == 0:
        return {"calibrated": False, "reason": "No evaluable predictions"}

    accuracy = correct / total
    avg_confidence = sum(confidence_scores) / len(confidence_scores)

    # calibration ratio: if accuracy < avg_confidence/100, we're overconfident
    calibration_ratio = accuracy / (avg_confidence / 100) if avg_confidence > 0 else 1.0

    return {
        "calibrated": True,
        "total_predictions": total,
        "correct_predictions": correct,
        "accuracy_pct": round(accuracy * 100, 1),
        "avg_confidence": round(avg_confidence, 1),
        "calibration_ratio": round(calibration_ratio, 2),
        "status": "overconfident" if calibration_ratio < 0.8 else ("underconfident" if calibration_ratio > 1.2 else "well-calibrated"),
        "suggested_adjustment": round((calibration_ratio - 1) * 100, 1),
    }


def clear_history(db: Session, ticker: str) -> int:
    """Get prediction history for a ticker."""
    stmt = (
        select(LLMHistory)
        .where(LLMHistory.ticker == ticker.upper())
        .order_by(LLMHistory.created_at.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "action": r.action,
            "buy_price": r.buy_price,
            "sell_price": r.sell_price,
            "stop_loss": r.stop_loss,
            "take_profit": r.take_profit,
            "confidence": r.confidence,
            "reasoning": r.reasoning,
            "model": r.model,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]


def build_messages_for_llm(
    db: Session,
    ticker: str,
    system_prompt: str,
    user_prompt: str,
    include_history: bool = True,
) -> list[dict]:
    """Build the messages array for OpenAI API with conversation history."""
    messages = [{"role": "system", "content": system_prompt}]

    if include_history:
        history = get_history(db, ticker, limit=10)
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_prompt})
    return messages


def clear_history(db: Session, ticker: str) -> int:
    """Clear conversation history for a ticker. Returns count deleted."""
    rows = db.execute(
        select(Conversation).where(Conversation.ticker == ticker.upper())
    ).scalars().all()
    count = len(rows)
    for r in rows:
        db.delete(r)
    db.commit()
    return count
