import pytest
from unittest.mock import patch, MagicMock, call


MOCK_PORTFOLIO = {
    "cash": 50.00,
    "holdings": [{"ticker": "MSFT", "shares": 0.1, "avg_buy_price_usd": 400.00, "total_cost_eur": 40.00}],
    "watchlist": ["NVDA"],
    "ticker_signals": {},
    "last_alert": None,
    "trade_log": [],
}
MOCK_PRICES = {"MSFT": {"price": 420.00, "pct_change": 1.5}}
MOCK_NEWS = {"MSFT": [], "NVDA": []}
MOCK_RESULT_HOLD = {
    "actions": [{"ticker": "MSFT", "action": "HOLD", "reasoning": "No catalyst"}],
    "watchlist_additions": [],
    "watchlist_removals": [],
}
MOCK_RESULT_BUY = {
    "actions": [{"ticker": "NVDA", "action": "BUY", "amount": "20.00", "headline": "AI demand", "reasoning": "Strong thesis"}],
    "watchlist_additions": [],
    "watchlist_removals": [],
}


def _patch_env():
    return patch.dict("os.environ", {
        "ANTHROPIC_API_KEY": "test-anthropic",
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "123",
        "NEWS_API_KEY": "test-news",
        "FINNHUB_API_KEY": "test-finnhub",
    })


def test_run_skips_when_market_closed():
    with _patch_env(), \
         patch("agent.main.is_market_open", return_value=False) as mock_open, \
         patch("agent.main.load_portfolio") as mock_load:
        from agent.main import run
        run()
        mock_open.assert_called_once()
        mock_load.assert_not_called()


def test_run_sends_hold_summary_when_all_hold():
    with _patch_env(), \
         patch("agent.main.is_market_open", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_trending_tickers", return_value=[]), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=MOCK_RESULT_HOLD), \
         patch("agent.main.save_portfolio") as mock_save, \
         patch("agent.main.send_message") as mock_send, \
         patch("agent.main.format_no_action", return_value="no action msg"):
        from agent.main import run
        run()
        mock_save.assert_called_once()
        mock_send.assert_called_once_with("test-token", "123", "no action msg")


def test_run_sends_individual_alerts_for_non_hold():
    with _patch_env(), \
         patch("agent.main.is_market_open", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_trending_tickers", return_value=[]), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=MOCK_RESULT_BUY), \
         patch("agent.main.save_portfolio"), \
         patch("agent.main.send_message") as mock_send, \
         patch("agent.main.format_alert", return_value="buy alert msg"):
        from agent.main import run
        run()
        mock_send.assert_called_once_with("test-token", "123", "buy alert msg")


def test_run_updates_watchlist_additions():
    result = {**MOCK_RESULT_HOLD, "watchlist_additions": ["AMD"], "watchlist_removals": []}
    with _patch_env(), \
         patch("agent.main.is_market_open", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_trending_tickers", return_value=[]), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=result), \
         patch("agent.main.save_portfolio") as mock_save, \
         patch("agent.main.send_message"), \
         patch("agent.main.format_no_action", return_value="msg"):
        from agent.main import run
        run()
        saved = mock_save.call_args[0][0]
        assert "AMD" in saved["watchlist"]


def test_run_updates_watchlist_removals():
    result = {**MOCK_RESULT_HOLD, "watchlist_additions": [], "watchlist_removals": ["NVDA"]}
    with _patch_env(), \
         patch("agent.main.is_market_open", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_trending_tickers", return_value=[]), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=result), \
         patch("agent.main.save_portfolio") as mock_save, \
         patch("agent.main.send_message"), \
         patch("agent.main.format_no_action", return_value="msg"):
        from agent.main import run
        run()
        saved = mock_save.call_args[0][0]
        assert "NVDA" not in saved["watchlist"]


def test_run_stores_ticker_signals():
    with _patch_env(), \
         patch("agent.main.is_market_open", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_trending_tickers", return_value=[]), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=MOCK_RESULT_HOLD), \
         patch("agent.main.save_portfolio") as mock_save, \
         patch("agent.main.send_message"), \
         patch("agent.main.format_no_action", return_value="msg"):
        from agent.main import run
        run()
        saved = mock_save.call_args[0][0]
        assert "ticker_signals" in saved
        assert "MSFT" in saved["ticker_signals"]
        assert saved["ticker_signals"]["MSFT"]["action"] == "HOLD"


def test_run_sends_error_message_on_exception():
    with _patch_env(), \
         patch("agent.main.is_market_open", return_value=True), \
         patch("agent.main.load_portfolio", side_effect=Exception("disk error")), \
         patch("agent.main.send_message") as mock_send:
        from agent.main import run
        with pytest.raises(Exception, match="disk error"):
            run()
        mock_send.assert_called_once()
        assert "error" in mock_send.call_args[0][2].lower()
