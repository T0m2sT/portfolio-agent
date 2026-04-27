import pytest
from unittest.mock import patch, MagicMock


MOCK_PORTFOLIO = {
    "cash": 4000.00,
    "holdings": [{"ticker": "MSFT", "shares": 0.1, "avg_buy_price_usd": 400.00, "total_cost_eur": 200.00, "bought_pct": 10}],
    "last_alert": None,
    "trade_log": [],
}
MOCK_PRICES = {"MSFT": {"price": 420.00, "pct_change": 1.5}}
MOCK_NEWS = {"__general__": ["Market rallies"], "MSFT": []}
MOCK_RESULT_HOLD = {
    "actions": [{"ticker": "MSFT", "action": "HOLD", "reasoning": "No catalyst"}],
    "overall_confidence": "low",
    "risks": [],
}
MOCK_RESULT_BUY = {
    "actions": [{"ticker": "NVDA", "action": "BUY", "amount": "20%", "headline": "AI demand", "reasoning": "Strong thesis"}],
    "overall_confidence": "high",
    "risks": [],
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
         patch("agent.main.get_market_session", return_value="regular"), \
         patch("agent.main.is_us_trading_day", return_value=False) as mock_open, \
         patch("agent.main.load_portfolio") as mock_load:
        from agent.main import run
        run()
        mock_open.assert_called_once()
        mock_load.assert_not_called()


def test_run_sends_hold_summary_when_all_hold():
    with _patch_env(), \
         patch("agent.main.get_market_session", return_value="regular"), \
         patch("agent.main.is_us_trading_day", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
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
         patch("agent.main.get_market_session", return_value="regular"), \
         patch("agent.main.is_us_trading_day", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=MOCK_RESULT_BUY), \
         patch("agent.main.save_portfolio"), \
         patch("agent.main.send_message") as mock_send, \
         patch("agent.main.format_alert", return_value="buy alert msg"):
        from agent.main import run
        run()
        mock_send.assert_called_once_with("test-token", "123", "buy alert msg")


def test_run_fetches_opportunity_prices():
    news_with_opp = {**MOCK_NEWS, "NVDA": ["Nvidia beats earnings"]}
    with _patch_env(), \
         patch("agent.main.get_market_session", return_value="regular"), \
         patch("agent.main.is_us_trading_day", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES) as mock_fetch_prices, \
         patch("agent.main.fetch_news", return_value=news_with_opp), \
         patch("agent.main.analyse", return_value=MOCK_RESULT_HOLD), \
         patch("agent.main.save_portfolio"), \
         patch("agent.main.send_message"), \
         patch("agent.main.format_no_action", return_value="msg"):
        from agent.main import run
        run()
        # Should have been called twice — once for held, once for opportunity tickers
        assert mock_fetch_prices.call_count == 2


def test_run_stores_last_alert():
    with _patch_env(), \
         patch("agent.main.get_market_session", return_value="regular"), \
         patch("agent.main.is_us_trading_day", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=MOCK_RESULT_BUY), \
         patch("agent.main.save_portfolio") as mock_save, \
         patch("agent.main.send_message"), \
         patch("agent.main.format_alert", return_value="alert"):
        from agent.main import run
        run()
        saved = mock_save.call_args[0][0]
        assert saved["last_alert"]["ticker"] == "NVDA"
        assert saved["last_alert"]["action"] == "BUY"


def test_run_stores_run_metadata():
    with _patch_env(), \
         patch("agent.main.get_market_session", return_value="regular"), \
         patch("agent.main.is_us_trading_day", return_value=True), \
         patch("agent.main.load_portfolio", return_value=MOCK_PORTFOLIO), \
         patch("agent.main.fetch_prices", return_value=MOCK_PRICES), \
         patch("agent.main.fetch_news", return_value=MOCK_NEWS), \
         patch("agent.main.analyse", return_value=MOCK_RESULT_HOLD), \
         patch("agent.main.save_portfolio") as mock_save, \
         patch("agent.main.send_message"), \
         patch("agent.main.format_no_action", return_value="msg"):
        from agent.main import run
        run()
        saved = mock_save.call_args[0][0]
        assert saved["last_market_session"] == "regular"
        assert "last_analysis_confidence" in saved
        assert "last_analysis_risks" in saved


def test_run_sends_error_message_on_exception():
    with _patch_env(), \
         patch("agent.main.get_market_session", return_value="regular"), \
         patch("agent.main.is_us_trading_day", return_value=True), \
         patch("agent.main.load_portfolio", side_effect=Exception("disk error")), \
         patch("agent.main.send_message") as mock_send:
        from agent.main import run
        with pytest.raises(Exception, match="disk error"):
            run()
        mock_send.assert_called_once()
        assert "error" in mock_send.call_args[0][2].lower()
