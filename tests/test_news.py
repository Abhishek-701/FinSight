import unittest
from unittest.mock import MagicMock, patch

from app import config
from app.tools import news, news_provider


class YFinanceNewsProviderTests(unittest.TestCase):
    """Parses the real yfinance .news shape (nested under "content", as of yfinance 1.4.x)."""

    def test_parses_real_shaped_response(self):
        raw = [{
            "content": {
                "title": "NVIDIA hits new high",
                "pubDate": "2026-07-10T12:00:00Z",
                "provider": {"displayName": "Reuters"},
                "canonicalUrl": {"url": "https://reuters.com/nvda-high"},
                "summary": "Shares rallied.",
            }
        }]
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.news = raw
            items = news_provider.YFinanceNewsProvider().headlines("NVDA", 8)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "NVIDIA hits new high")
        self.assertEqual(items[0]["publisher"], "Reuters")
        self.assertEqual(items[0]["published_at"], "2026-07-10T12:00:00Z")
        self.assertEqual(items[0]["url"], "https://reuters.com/nvda-high")

    def test_missing_provider_name_falls_back_to_url_domain(self):
        raw = [{"content": {"title": "X", "canonicalUrl": {"url": "https://www.fool.com/a"}}}]
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.news = raw
            items = news_provider.YFinanceNewsProvider().headlines("NVDA", 8)
        self.assertEqual(items[0]["publisher"], "fool.com")

    def test_entries_without_title_are_skipped(self):
        raw = [{"content": {"title": ""}}, {"content": {"title": "Real headline"}}]
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.news = raw
            items = news_provider.YFinanceNewsProvider().headlines("NVDA", 8)
        self.assertEqual(len(items), 1)

    def test_respects_limit(self):
        raw = [{"content": {"title": f"Headline {i}"}} for i in range(20)]
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.news = raw
            items = news_provider.YFinanceNewsProvider().headlines("NVDA", 3)
        self.assertEqual(len(items), 3)

    def test_no_news_returns_empty_list(self):
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.news = None
            items = news_provider.YFinanceNewsProvider().headlines("NVDA", 8)
        self.assertEqual(items, [])


class YahooRssNewsProviderTests(unittest.TestCase):
    _RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Tesla stock jumps</title>
  <link>https://fool.com/tsla-jumps?.tsrc=rss</link>
  <pubDate>Sun, 12 Jul 2026 01:22:00 +0000</pubDate>
  <description>Shares rose on delivery numbers.</description>
</item>
<item>
  <title>Tesla faces scrutiny</title>
  <link>https://reuters.com/tsla-scrutiny</link>
  <pubDate>Sat, 11 Jul 2026 10:00:00 +0000</pubDate>
  <description>Regulators are looking into it.</description>
</item>
</channel></rss>"""

    def test_parses_rss_items(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = self._RSS
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            items = news_provider.YahooRssNewsProvider().headlines("TSLA", 8)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Tesla stock jumps")
        self.assertEqual(items[0]["publisher"], "fool.com")
        self.assertIn("2026", items[0]["published_at"])

    def test_respects_limit(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = self._RSS
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            items = news_provider.YahooRssNewsProvider().headlines("TSLA", 1)
        self.assertEqual(len(items), 1)


class NewsHeadlinesToolTests(unittest.TestCase):
    """news_headlines() — caching, fallback chain, chunk shape. Mocked at the provider
    boundary (get_provider/get_fallback_provider), not yfinance/urllib directly."""

    def setUp(self):
        news._NEWS_CACHE.clear()

    def tearDown(self):
        news._NEWS_CACHE.clear()

    def _mock_provider(self, name, items=None, raises=False):
        provider = MagicMock()
        provider.name = name
        if raises:
            provider.headlines.side_effect = RuntimeError("boom")
        else:
            provider.headlines.return_value = items or []
        return provider

    @patch("app.tools.news.get_provider")
    def test_primary_provider_success(self, mock_get_provider):
        mock_get_provider.return_value = self._mock_provider(
            "yfinance", [{"title": "X", "publisher": "Reuters", "published_at": "2026-07-10", "url": "u"}]
        )
        result = news.news_headlines("NVDA")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["evidence"][0]["kind"], "news")
        self.assertTrue(result["evidence"][0]["chunk_id"].startswith("NVDA-NEWS-"))

    @patch("app.tools.news.get_fallback_provider")
    @patch("app.tools.news.get_provider")
    def test_falls_back_on_primary_exception(self, mock_get_provider, mock_get_fallback):
        mock_get_provider.return_value = self._mock_provider("yfinance", raises=True)
        mock_get_fallback.return_value = self._mock_provider(
            "yahoo_rss", [{"title": "Y", "publisher": "Fool", "published_at": "2026-07-10", "url": "u"}]
        )
        result = news.news_headlines("NVDA")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["source"], "yahoo_rss")

    @patch("app.tools.news.get_fallback_provider")
    @patch("app.tools.news.get_provider")
    def test_falls_back_on_empty_primary_result(self, mock_get_provider, mock_get_fallback):
        mock_get_provider.return_value = self._mock_provider("yfinance", [])
        mock_get_fallback.return_value = self._mock_provider(
            "yahoo_rss", [{"title": "Y", "publisher": "Fool", "published_at": "2026-07-10", "url": "u"}]
        )
        result = news.news_headlines("NVDA")
        self.assertEqual(result["data"]["source"], "yahoo_rss")
        mock_get_fallback.assert_called_once()

    @patch("app.tools.news.get_fallback_provider")
    @patch("app.tools.news.get_provider")
    def test_both_providers_empty_returns_empty_status_not_error(self, mock_get_provider, mock_get_fallback):
        mock_get_provider.return_value = self._mock_provider("yfinance", [])
        mock_get_fallback.return_value = self._mock_provider("yahoo_rss", [])
        result = news.news_headlines("NVDA")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["evidence"][0]["kind"], "news")  # still citable, just says no headlines
        self.assertIn("No recent headlines", result["evidence"][0]["text"])

    @patch("app.tools.news.get_fallback_provider")
    @patch("app.tools.news.get_provider")
    def test_both_providers_raise_returns_empty_not_crash(self, mock_get_provider, mock_get_fallback):
        mock_get_provider.return_value = self._mock_provider("yfinance", raises=True)
        mock_get_fallback.return_value = self._mock_provider("yahoo_rss", raises=True)
        result = news.news_headlines("NVDA")
        self.assertEqual(result["status"], "empty")

    @patch("app.tools.news.get_provider")
    def test_second_call_uses_cache(self, mock_get_provider):
        provider = self._mock_provider(
            "yfinance", [{"title": "X", "publisher": "Reuters", "published_at": "2026-07-10", "url": "u"}]
        )
        mock_get_provider.return_value = provider
        news.news_headlines("NVDA")
        result = news.news_headlines("NVDA")
        self.assertTrue(result["cached"])
        self.assertEqual(provider.headlines.call_count, 1)

    def test_missing_ticker_returns_structured_status(self):
        result = news.news_headlines(None)
        self.assertEqual(result["status"], "missing_ticker")

    @patch("app.tools.news.get_provider")
    def test_chunk_text_carries_no_causation_framing(self, mock_get_provider):
        mock_get_provider.return_value = self._mock_provider(
            "yfinance", [{"title": "X", "publisher": "Reuters", "published_at": "2026-07-10", "url": "u"}]
        )
        result = news.news_headlines("NVDA")
        text = result["evidence"][0]["text"]
        self.assertIn("not a verified cause", text)

    @patch("app.tools.news.get_provider")
    def test_tool_registered_in_registry(self, mock_get_provider):
        from app.tools.registry import TOOL_REGISTRY
        self.assertIn("news_headlines", TOOL_REGISTRY)
        self.assertEqual(TOOL_REGISTRY["news_headlines"].arg_spec["ticker"], "*")


if __name__ == "__main__":
    unittest.main()
