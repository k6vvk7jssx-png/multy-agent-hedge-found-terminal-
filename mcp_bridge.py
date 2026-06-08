"""
free_search.py (mcp_bridge.py)
Motore di ricerca 100% gratuito e senza API key.
Fonti: Google News RSS + yfinance .news endpoint.
Mantiene la stessa firma di mcp_brave_search() per compatibilità.
"""
import logging
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup
import yfinance as yf

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def google_news_rss(query: str, max_results: int = 6) -> list[dict]:
    """
    Cerca tramite Google News RSS (nessuna API key richiesta).
    Restituisce lista di dict con 'title', 'link', 'pubDate'.
    """
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    results = []
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            logger.warning(f"GoogleNewsRSS: HTTP {resp.status_code} per query '{query}'")
            return results
        soup = BeautifulSoup(resp.text, "xml")
        for item in soup.find_all("item")[:max_results]:
            title_tag = item.find("title")
            link_tag = item.find("link")
            date_tag = item.find("pubDate")
            source_tag = item.find("source")
            results.append({
                "title": title_tag.text.strip() if title_tag else "N/A",
                "link": link_tag.text.strip() if link_tag else "",
                "pubDate": date_tag.text.strip() if date_tag else "",
                "source": source_tag.text.strip() if source_tag else "Google News",
            })
    except Exception as e:
        logger.error(f"GoogleNewsRSS error per '{query}': {e}")
    return results


def yfinance_news(ticker: str, max_results: int = 5) -> list[dict]:
    """
    Recupera notizie societarie direttamente da Yahoo Finance (nessuna API key).
    yfinance 1.3+ annida i dati in article['content']. Questa funzione gestisce
    entrambe le strutture (piatta e annidata).
    Restituisce lista di dict con 'title', 'summary', 'link', 'publisher', 'pubDate'.
    """
    results = []
    try:
        stock = yf.Ticker(ticker)
        raw_news = stock.news or []
        for article in raw_news[:max_results]:
            if not isinstance(article, dict):
                continue
            # yfinance 1.3.x: struttura annidata in 'content'
            content = article.get("content") or {}
            if not isinstance(content, dict):
                content = {}
            # Estrazione campi con fallback alla struttura piatta (versioni precedenti)
            title = content.get("title") or article.get("title", "N/A")
            summary = content.get("summary") or article.get("summary", "")
            pub_date = content.get("pubDate") or article.get("providerPublishTime", "")
            # Provider
            provider_obj = content.get("provider") or {}
            provider = (provider_obj.get("displayName") if isinstance(provider_obj, dict) else str(provider_obj)) or "Yahoo Finance"
            # URL
            click_url_obj = content.get("clickThroughUrl") or {}
            click_url = (click_url_obj.get("url") if isinstance(click_url_obj, dict) else "") or article.get("link", "")
            if title and title != "N/A":
                results.append({
                    "title": str(title),
                    "summary": str(summary)[:300] if summary else "",
                    "link": str(click_url),
                    "publisher": str(provider),
                    "pubDate": str(pub_date)[:19] if pub_date else "",
                })
    except Exception as e:
        logger.error(f"yfinance_news error per '{ticker}': {e}")
    return results


def format_news_list(items: list[dict], mode: str = "news") -> str:
    """Formatta una lista di articoli/risultati in testo leggibile dagli agenti."""
    if not items:
        return "Nessun risultato trovato."
    lines = []
    for i, item in enumerate(items, 1):
        title = item.get("title", "N/A")
        link = item.get("link", "")
        date = item.get("pubDate", "") or item.get("displayTime", "")
        source = item.get("source") or item.get("publisher", "")
        summary = item.get("summary", "")
        line = f"{i}. [{title}]"
        if source:
            line += f" — {source}"
        if date:
            line += f" ({date[:10]})"
        if summary:
            line += f"\n   {summary[:200]}"
        if link:
            line += f"\n   {link}"
        lines.append(line)
    return "\n\n".join(lines)


def mcp_brave_search(query: str) -> str:
    """
    Interfaccia compatibile con il vecchio mcp_brave_search().
    Usa Google News RSS come backend gratuito senza API key.
    Estratto un po' di dati yfinance se la query contiene un ticker.
    """
    logger.info(f"FreeSearch: Google News RSS per query: '{query}'")
    items = google_news_rss(query, max_results=6)
    return format_news_list(items, mode="rss")


if __name__ == "__main__":
    print("=== TEST FreeSearch: Google News RSS ===")
    res = mcp_brave_search("Apple AAPL stock market risk")
    print(res)
    print("\n=== TEST yfinance_news: AAPL ===")
    news = yfinance_news("AAPL", max_results=3)
    print(format_news_list(news))
