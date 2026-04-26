import pytest
import json
from unittest.mock import patch, MagicMock


PORTFOLIO = {
    "cash": 60.00,
    "holdings": [{"ticker": "MSFT", "shares": 0.5, "avg_buy_price_usd": 400.00, "total_cost_eur": 40.00}],
    "watchlist": ["NVDA"],
    "last_run": "2026-04-26T10:00:00+00:00",
    "last_alert": {"ticker": "MSFT", "action": "BUY", "reasoning": "Strong AI thesis", "all_actions": []},
    "trade_log": [],
}


@pytest.fixture
def client():
    env = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "ANTHROPIC_API_KEY": "test-anthropic",
        "PORTFOLIO_RAW_URL": "https://raw.example.com/portfolio.json",
        "GITHUB_TOKEN": "test-gh",
        "GITHUB_REPO": "user/repo",
    }
    with patch.dict("os.environ", env):
        from bot.server import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


def _post(client, text):
    return client.post(
        "/webhook/test-token",
        json={"message": {"chat": {"id": "123"}, "text": text}},
        content_type="application/json",
    )


def test_webhook_ignores_empty_message(client):
    resp = client.post(
        "/webhook/test-token",
        json={"message": {}},
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_help_command(client):
    with patch("bot.server.send") as mock_send:
        resp = _post(client, "/help")
    assert resp.status_code == 200
    msg = mock_send.call_args[0][1]
    assert "/portfolio" in msg
    assert "/buy" in msg
    assert "/sell" in msg


def test_portfolio_command(client):
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/portfolio")
    assert resp.status_code == 200
    msg = mock_send.call_args[0][1]
    assert "MSFT" in msg
    assert "60.00" in msg


def test_reason_command_with_alert(client):
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/reason")
    assert resp.status_code == 200
    msg = mock_send.call_args[0][1]
    assert "Strong AI thesis" in msg
    assert "MSFT" in msg


def test_reason_command_no_alert(client):
    portfolio = {**PORTFOLIO, "last_alert": None}
    with patch("bot.server.get_portfolio", return_value=portfolio), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/reason")
    assert resp.status_code == 200
    msg = mock_send.call_args[0][1]
    assert "No recent alert" in msg


def test_log_command_no_trades(client):
    portfolio = {**PORTFOLIO, "trade_log": []}
    with patch("bot.server.get_portfolio", return_value=portfolio), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/log")
    assert resp.status_code == 200
    assert "No closed trades" in mock_send.call_args[0][1]


def test_log_command_with_trades(client):
    portfolio = {**PORTFOLIO, "trade_log": [
        {"ticker": "NVDA", "shares": 1.0, "pnl": 25.00, "price_usd": 880.00, "cost_eur": 40.00, "proceeds_eur": 65.00, "closed_at": "2026-04-20"}
    ]}
    with patch("bot.server.get_portfolio", return_value=portfolio), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/log")
    assert resp.status_code == 200
    msg = mock_send.call_args[0][1]
    assert "NVDA" in msg
    assert "25.00" in msg


def test_ask_command(client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="MSFT looks good.")]
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.anthropic.Anthropic") as mock_anthropic, \
         patch("bot.server.send") as mock_send:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        resp = _post(client, "/ask what should I do with MSFT?")
    assert resp.status_code == 200
    assert "MSFT looks good." in mock_send.call_args[0][1]


def test_reset_command(client):
    with patch("bot.server.save_portfolio_github") as mock_save, \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/reset")
    assert resp.status_code == 200
    saved = mock_save.call_args[0][0]
    assert saved["cash"] == 100.0
    assert saved["holdings"] == []
    assert "reset" in mock_send.call_args[0][1].lower()


def test_status_command(client):
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/status")
    assert resp.status_code == 200
    msg = mock_send.call_args[0][1]
    assert "Last run" in msg
    assert "Next run" in msg


def test_buy_command_success(client):
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.apply_action", return_value={**PORTFOLIO, "cash": 20.00}) as mock_action, \
         patch("bot.server.save_portfolio_github") as mock_save, \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/buy NVDA 0.5 880.00 40.00")
    assert resp.status_code == 200
    assert "BUY recorded" in mock_send.call_args[0][1]
    mock_save.assert_called_once()


def test_buy_command_insufficient_cash(client):
    portfolio = {**PORTFOLIO, "cash": 5.00}
    with patch("bot.server.get_portfolio", return_value=portfolio), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/buy NVDA 0.5 880.00 40.00")
    assert resp.status_code == 200
    assert "Not enough cash" in mock_send.call_args[0][1]


def test_buy_command_wrong_args(client):
    with patch("bot.server.send") as mock_send:
        resp = _post(client, "/buy NVDA")
    assert resp.status_code == 200
    assert "Usage" in mock_send.call_args[0][1]


def test_buy_command_invalid_numbers(client):
    with patch("bot.server.send") as mock_send:
        resp = _post(client, "/buy NVDA abc 880.00 40.00")
    assert resp.status_code == 200
    assert "positive numbers" in mock_send.call_args[0][1]


def test_sell_command_success(client):
    trade = {"ticker": "MSFT", "shares": 0.25, "pnl": 5.00, "price_usd": 420.00, "cost_eur": 20.00, "proceeds_eur": 25.00}
    updated = {**PORTFOLIO, "cash": 85.00, "trade_log": [trade]}
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.apply_action", return_value=updated), \
         patch("bot.server.save_portfolio_github") as mock_save, \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/sell MSFT 50% 420.00 25.00")
    assert resp.status_code == 200
    assert "SELL recorded" in mock_send.call_args[0][1]
    mock_save.assert_called_once()


def test_sell_command_short_with_share_count(client):
    trade = {"ticker": "TSLA", "shares": 1.0, "pnl": 23.00, "price_usd": 250.00, "cost_eur": 0.0, "proceeds_eur": 23.00, "short": True}
    updated = {**PORTFOLIO, "cash": 83.00, "trade_log": [trade]}
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.apply_action", return_value=updated), \
         patch("bot.server.save_portfolio_github"), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/sell TSLA 1 250.00 23.00")
    assert resp.status_code == 200
    assert "SHORT recorded" in mock_send.call_args[0][1]

def test_sell_command_short_rejects_all_on_not_held(client):
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/sell TSLA ALL 880.00 100.00")
    assert resp.status_code == 200
    assert "not held" in mock_send.call_args[0][1]

def test_sell_command_short_rejects_pct_on_not_held(client):
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/sell TSLA 50% 880.00 100.00")
    assert resp.status_code == 200
    assert "not held" in mock_send.call_args[0][1]


def test_sell_command_wrong_args(client):
    with patch("bot.server.send") as mock_send:
        resp = _post(client, "/sell MSFT")
    assert resp.status_code == 200
    assert "Usage" in mock_send.call_args[0][1]


def test_sell_command_invalid_amount(client):
    with patch("bot.server.get_portfolio", return_value=PORTFOLIO), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/sell MSFT bad_amount 420.00 25.00")
    assert resp.status_code == 200
    assert "percentage" in mock_send.call_args[0][1].lower() or "number" in mock_send.call_args[0][1].lower()


def test_webhook_rejects_invalid_secret(client):
    with patch("bot.server.TELEGRAM_WEBHOOK_SECRET", "correct-secret"):
        resp = client.post(
            "/webhook/test-token",
            json={"message": {"chat": {"id": "123"}, "text": "/help"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            content_type="application/json",
        )
    assert resp.status_code == 401

def test_webhook_accepts_valid_secret(client):
    with patch("bot.server.TELEGRAM_WEBHOOK_SECRET", "correct-secret"), \
         patch("bot.server.send"):
        resp = client.post(
            "/webhook/test-token",
            json={"message": {"chat": {"id": "123"}, "text": "/help"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "correct-secret"},
            content_type="application/json",
        )
    assert resp.status_code == 200

def test_webhook_exception_sends_error(client):
    with patch("bot.server.get_portfolio", side_effect=Exception("db error")), \
         patch("bot.server.send") as mock_send:
        resp = _post(client, "/portfolio")
    assert resp.status_code == 200
    assert "error" in mock_send.call_args[0][1].lower()


def test_notifier_format_no_action():
    from agent.notifier import format_no_action
    actions = [
        {"ticker": "MSFT", "action": "HOLD", "reasoning": "No catalyst"},
        {"ticker": "NVDA", "action": "HOLD", "reasoning": "Waiting for entry"},
    ]
    prices = {"MSFT": {"price": 420.00, "pct_change": 1.5}, "NVDA": {"price": 880.00, "pct_change": -0.5}}
    msg = format_no_action(actions, prices)
    assert "NO ACTION" in msg
    assert "MSFT" in msg
    assert "NVDA" in msg
    assert "No catalyst" in msg
    assert "$420.00" in msg
