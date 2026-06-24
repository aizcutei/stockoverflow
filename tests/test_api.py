"""End-to-end API tests using httpx."""

import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app


@pytest.fixture
def client():
    """Create async test client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_search_endpoint(client):
    response = await client.get("/api/search?q=AAPL")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        assert "ticker" in data[0]
        assert "name" in data[0]


@pytest.mark.anyio
async def test_stock_endpoint(client):
    response = await client.get("/api/stock/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert "info" in data
    assert "candles" in data
    assert "indicators" in data
    assert "overall" in data
    assert len(data["candles"]) > 0
    assert len(data["indicators"]) > 0


@pytest.mark.anyio
async def test_stock_with_period(client):
    response = await client.get("/api/stock/MSFT?period=1y")
    assert response.status_code == 200
    data = response.json()
    assert len(data["candles"]) > 100


@pytest.mark.anyio
async def test_stock_invalid(client):
    response = await client.get("/api/stock/INVALID_XYZ_999")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data


@pytest.mark.anyio
async def test_cached_endpoint(client):
    # first ensure data exists
    await client.get("/api/stock/AAPL")
    response = await client.get("/api/stock/AAPL/cached")
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert "info" in data


@pytest.mark.anyio
async def test_news_endpoint(client):
    response = await client.get("/api/stock/AAPL/news?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.anyio
async def test_financials_endpoint(client):
    response = await client.get("/api/stock/AAPL/financials")
    assert response.status_code == 200
    data = response.json()
    assert "financials" in data
    assert "earnings" in data


@pytest.mark.anyio
async def test_factor_library(client):
    response = await client.get("/api/factors/library")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "name" in data[0]
    assert "expression" in data[0]


@pytest.mark.anyio
async def test_factor_eval(client):
    response = await client.post(
        "/api/factors/eval/AAPL",
        json={"expression": "rsi(14) < 50"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "type" in data
    assert "values" in data


@pytest.mark.anyio
async def test_factor_eval_invalid(client):
    response = await client.post(
        "/api/factors/eval/AAPL",
        json={"expression": "nonexistent_func()"},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_backtest_endpoint(client):
    response = await client.post(
        "/api/backtest/AAPL",
        json={
            "buy_expr": "rsi(14) < 30",
            "sell_expr": "rsi(14) > 70",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_return" in data
    assert "equity_curve" in data
    assert "trades" in data


@pytest.mark.anyio
async def test_backtest_invalid_expr(client):
    response = await client.post(
        "/api/backtest/AAPL",
        json={
            "buy_expr": "invalid()",
            "sell_expr": "rsi(14) > 70",
        },
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_llm_config(client):
    response = await client.get("/api/llm/config")
    assert response.status_code == 200
    data = response.json()
    assert "base_url" in data
    assert "model" in data


@pytest.mark.anyio
async def test_llm_models(client):
    response = await client.get("/api/llm/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert len(data) > 0


@pytest.mark.anyio
async def test_paper_account(client):
    response = await client.get("/api/paper/account")
    assert response.status_code == 200
    data = response.json()
    assert "cash" in data
    assert "total_equity" in data
    assert "positions" in data


@pytest.mark.anyio
async def test_paper_order(client):
    response = await client.post(
        "/api/paper/order",
        json={
            "ticker": "TEST",
            "side": "buy",
            "quantity": 5,
            "price": 100.0,
            "reason": "API test",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "trade_id" in data
    assert data["ticker"] == "TEST"


@pytest.mark.anyio
async def test_paper_trades(client):
    response = await client.get("/api/paper/trades")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.anyio
async def test_paper_stats(client):
    response = await client.get("/api/paper/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_trades" in data


@pytest.mark.anyio
async def test_dashboard(client):
    response = await client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "account" in data
    assert "recent_stocks" in data


@pytest.mark.anyio
async def test_fetch_history(client):
    response = await client.get("/api/stock/AAPL/fetch-history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.anyio
async def test_index_page(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.anyio
async def test_stock_page_routing(client):
    response = await client.get("/stock/AAPL")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.anyio
async def test_swagger_docs(client):
    response = await client.get("/docs")
    assert response.status_code == 200
