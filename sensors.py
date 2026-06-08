"""
sensors.py — Data Extraction Layer
Fornisce dati fondamentali, legali, trimestrali, di sentiment e insider
agli agenti CrewAI. Tutti i dati vengono serializzati in JSON sicuro.
Fallback: se SEC non riesce (ticker non-US / rate limit), 
vengono usate Google News RSS + yfinance news.
"""
import json
import math
import time
import random
import logging
import re
import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import yfinance as yf
from sec_edgar_downloader import Downloader

# Import motore di ricerca gratuito (Google News RSS)
from mcp_bridge import google_news_rss, yfinance_news, format_news_list

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ==========================================================
# HELPER: Sanitizzatore JSON Ricorsivo
# Converte pandas.Timestamp, numpy.int64, NaN, NaT, datetime, ecc.
# in tipi Python nativi JSON-serializzabili.
# ==========================================================
def sanitize_json(obj):
    """Ricorsivamente trasforma qualunque oggetto in un tipo JSON-safe."""
    # Pandas/numpy imports tentativo (potrebbero non essere installati)
    try:
        import numpy as np
        import pandas as pd

        if isinstance(obj, (pd.Timestamp, pd.NaT.__class__)):
            try:
                return obj.isoformat() if not pd.isnull(obj) else "N/A"
            except Exception:
                return "N/A"
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            if math.isnan(obj) or math.isinf(obj):
                return "N/A"
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return [sanitize_json(v) for v in obj.tolist()]
        if isinstance(obj, pd.Series):
            return {str(k): sanitize_json(v) for k, v in obj.items()}
        if isinstance(obj, pd.DataFrame):
            return {str(k): sanitize_json(v) for k, v in obj.to_dict().items()}
    except ImportError:
        pass

    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return "N/A"
        return obj
    # Fallback generico: converti in stringa
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def safe_json_dumps(data: dict) -> str:
    """Serializza usando sanitize_json per garantire zero errori di serializzazione."""
    return json.dumps(sanitize_json(data), indent=2, ensure_ascii=False)


# ==========================================================
# CLASSE: QuantSensor
# ==========================================================
class QuantSensor:
    CACHE_TTL_SECONDS = 3600

    @staticmethod
    def get_from_cache(ticker_symbol: str) -> dict:
        """Legge la cache locale se valida (TTL < 1 ora)."""
        cache_file = Path(f"cache_{ticker_symbol}.json")
        if cache_file.exists():
            file_age = time.time() - cache_file.stat().st_mtime
            if file_age < QuantSensor.CACHE_TTL_SECONDS:
                logger.info(f"QuantSensor: Cache valida per {ticker_symbol} (età: {int(file_age)}s).")
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logger.warning(f"QuantSensor: Errore lettura cache {ticker_symbol}: {e}")
        return None

    @staticmethod
    def save_to_cache(ticker_symbol: str, data: dict):
        """Salva i dati estratti nella cache locale."""
        cache_file = Path(f"cache_{ticker_symbol}.json")
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(safe_json_dumps(data))
        except Exception as e:
            logger.warning(f"QuantSensor: Errore salvataggio cache {ticker_symbol}: {e}")

    @staticmethod
    def extract(ticker_symbol: str) -> str:
        """
        Estrae metriche fondamentali complete da yfinance.
        Tutti i dati vengono sanitizzati prima della serializzazione JSON.
        """
        cached_data = QuantSensor.get_from_cache(ticker_symbol)
        if cached_data:
            return json.dumps(cached_data, indent=2, ensure_ascii=False)

        result = {"ticker": ticker_symbol, "success": False, "data": {}, "error": None}

        try:
            logger.info(f"QuantSensor: Estrazione dati yfinance FULL per {ticker_symbol}...")
            stock = yf.Ticker(ticker_symbol)
            info = stock.info

            def df_to_dict(df, cols=3):
                """Converte un DataFrame yfinance in dizionario JSON-safe (ultimi N anni)."""
                if df is None or df.empty:
                    return {}
                sliced = df.iloc[:, :cols].copy()
                sliced.columns = [str(c).split(" ")[0] for c in sliced.columns]
                return sanitize_json(sliced.to_dict())

            # Income Statement (3 anni)
            income_annual = df_to_dict(stock.income_stmt, 3)
            # Cash Flow (3 anni)
            cashflow_annual = df_to_dict(stock.cashflow, 3)
            # Balance Sheet (3 anni)
            balance_annual = df_to_dict(stock.balance_sheet, 3)

            # Earnings History (Surprise EPS trimestrali)
            earnings_hist = {}
            try:
                eh = stock.earnings_history
                if eh is not None and not eh.empty:
                    eh_clean = eh.tail(8).copy()
                    eh_clean.index = [str(i).split(" ")[0] for i in eh_clean.index]
                    cols_wanted = [c for c in ["epsEstimate", "epsActual", "surprisePercent"] if c in eh_clean.columns]
                    earnings_hist = sanitize_json(eh_clean[cols_wanted].to_dict())
            except Exception as e:
                logger.warning(f"QuantSensor: Earnings history non disponibile per {ticker_symbol}: {e}")

            # Prossimi eventi (Calendar)
            calendar_data = {}
            try:
                cal = stock.calendar
                if cal:
                    if hasattr(cal, 'to_dict'):
                        calendar_data = sanitize_json(cal.to_dict())
                    elif isinstance(cal, dict):
                        calendar_data = sanitize_json(cal)
            except Exception as e:
                logger.warning(f"QuantSensor: Calendar non disponibile per {ticker_symbol}: {e}")

            # Notizie recenti da yfinance
            recent_news = []
            try:
                raw = yfinance_news(ticker_symbol, max_results=4)
                recent_news = [
                    {"title": n.get("title", ""), "summary": n.get("summary", ""), "pubDate": n.get("pubDate", "")}
                    for n in raw
                ]
            except Exception as e:
                logger.warning(f"QuantSensor: News non disponibili per {ticker_symbol}: {e}")

            result["data"] = sanitize_json({
                # VALUTAZIONE
                "trailingPE":             info.get("trailingPE"),
                "forwardPE":              info.get("forwardPE"),
                "priceToSales":           info.get("priceToSalesTrailing12Months"),
                "priceToBook":            info.get("priceToBook"),
                "enterpriseToEbitda":     info.get("enterpriseToEbitda"),
                "enterpriseValue":        info.get("enterpriseValue"),
                "marketCap":              info.get("marketCap"),
                "currentPrice":           info.get("currentPrice") or info.get("regularMarketPrice"),
                "52weekHigh":             info.get("fiftyTwoWeekHigh"),
                "52weekLow":              info.get("fiftyTwoWeekLow"),
                # PROFITTABILITÀ
                "ebitda":                 info.get("ebitda"),
                "grossMargins":           info.get("grossMargins"),
                "operatingMargins":       info.get("operatingMargins"),
                "profitMargins":          info.get("profitMargins"),
                "returnOnEquity":         info.get("returnOnEquity"),
                "returnOnAssets":         info.get("returnOnAssets"),
                # LIQUIDITÀ E DEBITO
                "totalDebt":              info.get("totalDebt"),
                "totalCash":              info.get("totalCash"),
                "debtToEquity":           info.get("debtToEquity"),
                "currentRatio":           info.get("currentRatio"),
                "quickRatio":             info.get("quickRatio"),
                "freeCashflow":           info.get("freeCashflow"),
                "operatingCashflow":      info.get("operatingCashflow"),
                # CRESCITA
                "revenueGrowth":          info.get("revenueGrowth"),
                "earningsGrowth":         info.get("earningsGrowth"),
                "earningsQuarterlyGrowth": info.get("earningsQuarterlyGrowth"),
                # BILANCI COMPLETI
                "income_stmt_annual":     income_annual,
                "cashflow_annual":        cashflow_annual,
                "balance_sheet_annual":   balance_annual,
                # EARNINGS SURPRISE
                "earnings_history":       earnings_hist,
                # PROSSIMI EVENTI
                "calendar":               calendar_data,
                # NOTIZIE RECENTI
                "recent_news":            recent_news,
            })
            result["success"] = True
            QuantSensor.save_to_cache(ticker_symbol, result)

        except Exception as e:
            logger.error(f"QuantSensor: Errore estrazione {ticker_symbol}: {str(e)}")
            result["error"] = str(e)
        finally:
            sleep_time = random.uniform(2.0, 4.0)
            logger.info(f"QuantSensor: Pausa anti-ban di {sleep_time:.2f}s...")
            time.sleep(sleep_time)

        return safe_json_dumps(result)


# ==========================================================
# CLASSE: LegalSensor
# ==========================================================
class LegalSensor:
    SEC_DOWNLOAD_DIR = "sec_filings"
    USER_AGENT_COMPANY = "HedgeFund"
    USER_AGENT_EMAIL = "admin@local.dev"
    MAX_TEXT_LENGTH = 7000

    @staticmethod
    def _fallback_web_search(ticker: str) -> dict:
        """
        Fallback: usa Google News RSS per cercare rischi legali e annual report
        quando SEC EDGAR non riesce a scaricare il 10-K (ticker non-US, rate limit, ecc.).
        """
        logger.info(f"LegalSensor: Attivazione fallback Google News RSS per {ticker}...")
        queries = [
            f"{ticker} annual report risk factors legal proceedings 2024 2025",
            f"{ticker} lawsuit legal risk SEC filing regulatory",
        ]
        all_text = []
        for q in queries:
            items = google_news_rss(q, max_results=4)
            all_text.append(f"--- Query: {q} ---\n" + format_news_list(items))
            time.sleep(1.5)

        combined = "\n\n".join(all_text)
        return {
            "source": "FALLBACK: Google News RSS (SEC non disponibile)",
            "risk_factors": combined[:LegalSensor.MAX_TEXT_LENGTH],
            "legal_proceedings": "Dati legali ottenuti tramite fallback web search. Per dettagli precisi consultare il report annuale ufficiale.",
        }

    @staticmethod
    def extract(ticker: str) -> str:
        result = {"ticker": ticker, "success": False, "data": {}, "error": None}

        try:
            logger.info(f"LegalSensor: Avvio download 10-K per {ticker}...")
            dl = Downloader(LegalSensor.USER_AGENT_COMPANY, LegalSensor.USER_AGENT_EMAIL, LegalSensor.SEC_DOWNLOAD_DIR)
            num_downloaded = dl.get("10-K", ticker, limit=1)

            if num_downloaded == 0:
                logger.warning(f"LegalSensor: Nessun 10-K trovato per {ticker}. Attivazione fallback.")
                result["data"] = LegalSensor._fallback_web_search(ticker)
                result["success"] = True
                result["error"] = "10-K non trovato su SEC EDGAR. Dati da Google News RSS (fallback)."
                return safe_json_dumps(result)

            base_path = Path(LegalSensor.SEC_DOWNLOAD_DIR) / "sec-edgar-filings" / ticker / "10-K"
            html_files = list(base_path.rglob("*.html")) + list(base_path.rglob("*.txt"))

            if not html_files:
                logger.warning(f"LegalSensor: File 10-K non trovati su disco per {ticker}. Fallback.")
                result["data"] = LegalSensor._fallback_web_search(ticker)
                result["success"] = True
                result["error"] = "File 10-K non trovati su disco. Dati da Google News RSS (fallback)."
                return safe_json_dumps(result)

            primary_file = html_files[0]
            logger.info(f"LegalSensor: Parsing documento {primary_file}...")

            with open(primary_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            soup = BeautifulSoup(content, 'html.parser')
            text_content = soup.get_text(separator=' ', strip=True)

            # Estrazione euristica sezioni Item 1A e Item 3
            item_1a_match = re.search(
                r'(?i)item\s+1a\.?\s+risk\s+factors(.*?)(?:item\s+1b|item\s+2)',
                text_content, re.DOTALL
            )
            item_3_match = re.search(
                r'(?i)item\s+3\.?\s+legal\s+proceedings(.*?)(?:item\s+4)',
                text_content, re.DOTALL
            )

            risk_factors = item_1a_match.group(1).strip() if item_1a_match else ""
            legal_proceedings = item_3_match.group(1).strip() if item_3_match else ""

            # Se le sezioni sono troppo corte, applica fallback web
            if len(risk_factors) < 200 and len(legal_proceedings) < 200:
                logger.warning(f"LegalSensor: Sezioni SEC troppo corte, integrazione con web search per {ticker}.")
                web_data = LegalSensor._fallback_web_search(ticker)
                result["data"] = {
                    "source": "SEC EDGAR + Google News RSS fallback",
                    "risk_factors": (text_content[:4000] + "\n\n" + web_data["risk_factors"])[:LegalSensor.MAX_TEXT_LENGTH],
                    "legal_proceedings": web_data["legal_proceedings"],
                }
            else:
                result["data"] = {
                    "source": "SEC EDGAR 10-K",
                    "risk_factors": risk_factors[:LegalSensor.MAX_TEXT_LENGTH],
                    "legal_proceedings": legal_proceedings[:4000],
                }

            result["success"] = True

        except Exception as e:
            logger.error(f"LegalSensor: Errore fatale per {ticker}: {str(e)}")
            # Tenta comunque il fallback web
            try:
                result["data"] = LegalSensor._fallback_web_search(ticker)
                result["success"] = True
                result["error"] = f"Errore SEC, fallback attivato: {str(e)}"
            except Exception as e2:
                result["error"] = f"Errore critico: {str(e)} | Fallback fallito: {str(e2)}"

        return safe_json_dumps(result)


# ==========================================================
# CLASSE: QuarterlySensor
# ==========================================================
class QuarterlySensor:
    SEC_DOWNLOAD_DIR = "sec_filings"
    USER_AGENT_COMPANY = "HedgeFund"
    USER_AGENT_EMAIL = "admin@local.dev"
    MAX_TEXT_LENGTH = 6000

    @staticmethod
    def _fallback_web_search(ticker: str) -> dict:
        """
        Fallback: usa Google News RSS + yfinance news per trovare informazioni
        sugli ultimi utili trimestrali quando la SEC non riesce a scaricare il 10-Q.
        """
        logger.info(f"QuarterlySensor: Attivazione fallback Google News RSS per {ticker}...")
        queries = [
            f"{ticker} quarterly earnings results Q1 Q2 Q3 2024 2025",
            f"{ticker} revenue management guidance quarterly report earnings call",
        ]
        all_text = []
        for q in queries:
            items = google_news_rss(q, max_results=4)
            all_text.append(f"--- Query: {q} ---\n" + format_news_list(items))
            time.sleep(1.5)

        # Integra anche le notizie yfinance
        yf_news = yfinance_news(ticker, max_results=5)
        if yf_news:
            all_text.append("--- Yahoo Finance News ---\n" + format_news_list(yf_news))

        combined = "\n\n".join(all_text)
        return {
            "form_type": "FALLBACK: Google News RSS + Yahoo Finance News (10-Q non disponibile)",
            "source_file": "N/A",
            "mda_management_discussion": combined[:QuarterlySensor.MAX_TEXT_LENGTH],
            "risk_factors_update": "Dati trimestrali ottenuti tramite fallback web search. Per dettagli precisi consultare il report trimestrale ufficiale.",
        }

    @staticmethod
    def extract(ticker: str) -> str:
        result = {"ticker": ticker, "success": False, "data": {}, "error": None}

        try:
            logger.info(f"QuarterlySensor: Avvio download ultimo 10-Q per {ticker}...")
            dl = Downloader(QuarterlySensor.USER_AGENT_COMPANY, QuarterlySensor.USER_AGENT_EMAIL, QuarterlySensor.SEC_DOWNLOAD_DIR)
            num_downloaded = dl.get("10-Q", ticker, limit=1)

            if num_downloaded == 0:
                logger.warning(f"QuarterlySensor: Nessun 10-Q trovato per {ticker}. Fallback attivato.")
                result["data"] = QuarterlySensor._fallback_web_search(ticker)
                result["success"] = True
                result["error"] = "10-Q non trovato su SEC EDGAR. Dati da Google News RSS (fallback)."
                return safe_json_dumps(result)

            base_path = Path(QuarterlySensor.SEC_DOWNLOAD_DIR) / "sec-edgar-filings" / ticker / "10-Q"
            html_files = (
                list(base_path.rglob("*.html")) +
                list(base_path.rglob("*.htm")) +
                list(base_path.rglob("*.txt"))
            )

            if not html_files:
                logger.warning(f"QuarterlySensor: File 10-Q non trovati su disco per {ticker}. Fallback.")
                result["data"] = QuarterlySensor._fallback_web_search(ticker)
                result["success"] = True
                result["error"] = "File 10-Q non trovati su disco. Dati da Google News RSS (fallback)."
                return safe_json_dumps(result)

            html_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            primary_file = html_files[0]
            logger.info(f"QuarterlySensor: Parsing {primary_file.name}...")

            with open(primary_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            soup = BeautifulSoup(content, 'html.parser')
            text_content = soup.get_text(separator=' ', strip=True)

            mda_match = re.search(
                r'(?i)item\s+2\.?\s+management.{0,30}discussion(.*?)(?:item\s+3|item\s+4)',
                text_content, re.DOTALL
            )
            risk_match = re.search(
                r'(?i)item\s+1a\.?\s+risk\s+factors(.*?)(?:item\s+1b|item\s+2|item\s+3)',
                text_content, re.DOTALL
            )

            mda_text = mda_match.group(1).strip() if mda_match else ""
            risk_text = risk_match.group(1).strip() if risk_match else ""

            # Se MD&A troppo corta, integra con web
            if len(mda_text) < 300:
                logger.warning(f"QuarterlySensor: MD&A troppo corta per {ticker}, integrazione web.")
                web_data = QuarterlySensor._fallback_web_search(ticker)
                mda_text = (mda_text + "\n\n" + web_data["mda_management_discussion"])[:QuarterlySensor.MAX_TEXT_LENGTH]

            result["data"] = {
                "form_type": "10-Q (SEC EDGAR)",
                "source_file": str(primary_file),
                "mda_management_discussion": mda_text[:QuarterlySensor.MAX_TEXT_LENGTH],
                "risk_factors_update": risk_text[:3000] if risk_text else "Nessun aggiornamento Risk Factors nel 10-Q corrente.",
            }
            result["success"] = True
            logger.info(f"QuarterlySensor: Estrazione 10-Q completata per {ticker}.")

        except Exception as e:
            logger.error(f"QuarterlySensor: Errore fatale per {ticker}: {str(e)}")
            try:
                result["data"] = QuarterlySensor._fallback_web_search(ticker)
                result["success"] = True
                result["error"] = f"Errore SEC, fallback attivato: {str(e)}"
            except Exception as e2:
                result["error"] = f"Errore critico: {str(e)} | Fallback fallito: {str(e2)}"

        return safe_json_dumps(result)


# ==========================================================
# CLASSE: AlternativeDataSensor
# ==========================================================
class AlternativeDataSensor:
    """
    Analisi del sentiment retail e notizie alternative.
    Usa Google News RSS + Yahoo Finance News (nessuna API key richiesta).
    """

    @staticmethod
    def extract(ticker: str) -> str:
        logger.info(f"AltDataSensor: Ricerca notizie e sentiment per {ticker}...")

        # 1. Notizie societarie da Yahoo Finance
        yf_news_items = yfinance_news(ticker, max_results=5)
        yf_formatted = format_news_list(yf_news_items) if yf_news_items else "Nessuna notizia yfinance disponibile."

        # 2. Sentiment notizie da Google News RSS (focus retail/social)
        queries = [
            f"{ticker} stock forum reddit wallstreetbets opinion sentiment",
            f"{ticker} stock news analyst opinion bullish bearish",
        ]
        news_texts = []
        for q in queries:
            items = google_news_rss(q, max_results=4)
            if items:
                news_texts.append(f"--- {q} ---\n" + format_news_list(items))
            time.sleep(1.0)

        combined_sentiment = "\n\n".join(news_texts) if news_texts else "Nessun risultato disponibile."

        result = {
            "ticker": ticker,
            "success": True,
            "data": {
                "source": "Yahoo Finance News + Google News RSS (nessuna API key)",
                "yfinance_news": yf_formatted,
                "web_sentiment_search": combined_sentiment,
            }
        }

        return safe_json_dumps(result)


# ==========================================================
# CLASSE: InsiderSensor
# ==========================================================
class InsiderSensor:
    """
    Estrae dati insider trading, institutional holders e short interest.
    Tutta la serializzazione usa sanitize_json per prevenire errori Timestamp.
    """

    @staticmethod
    def extract(ticker_symbol: str) -> str:
        logger.info(f"InsiderSensor: Estrazione dati Insider e Ownership per {ticker_symbol}...")
        result = {"ticker": ticker_symbol, "success": False, "data": {}, "error": None}

        try:
            stock = yf.Ticker(ticker_symbol)

            # 1. Insider Transactions (Acquisti/Vendite recenti)
            insider_trans = []
            try:
                df_it = stock.insider_transactions
                if df_it is not None and not df_it.empty:
                    df_it_clean = df_it.head(15).copy()
                    # Converti 'Start Date' (Timestamp) in stringa
                    if 'Start Date' in df_it_clean.columns:
                        df_it_clean['Start Date'] = df_it_clean['Start Date'].astype(str)
                    # Applica sanitizzazione globale prima di to_dict
                    insider_trans = sanitize_json(df_it_clean.to_dict(orient='records'))
            except Exception as e:
                logger.warning(f"InsiderSensor: Insider transactions non disponibili: {e}")

            # 2. Institutional Holders
            inst_holders = []
            try:
                df_ih = stock.institutional_holders
                if df_ih is not None and not df_ih.empty:
                    inst_holders = sanitize_json(df_ih.head(10).to_dict(orient='records'))
            except Exception as e:
                logger.warning(f"InsiderSensor: Institutional holders non disponibili: {e}")

            # 3. Short Interest
            info = stock.info
            short_data = sanitize_json({
                "shortPercentOfFloat":   info.get("shortPercentOfFloat"),
                "shortRatio":            info.get("shortRatio"),
                "sharesShort":           info.get("sharesShort"),
                "sharesShortPriorMonth": info.get("sharesShortPriorMonth"),
            })

            result["data"] = {
                "insider_transactions":   insider_trans,
                "institutional_holders":  inst_holders,
                "short_interest":         short_data,
            }
            result["success"] = True

        except Exception as e:
            logger.error(f"InsiderSensor: Errore fatale per {ticker_symbol}: {str(e)}")
            result["error"] = str(e)

        return safe_json_dumps(result)


# ==========================================================
# ENTRY POINT (solo testing diretto, NON viene eseguito in import)
# ==========================================================
if __name__ == "__main__":
    test_ticker = 'AAPL'
    print(f"\n--- TEST QuantSensor ({test_ticker}) ---")
    print(QuantSensor.extract(test_ticker))

    print(f"\n--- TEST InsiderSensor ({test_ticker}) ---")
    print(InsiderSensor.extract(test_ticker))

    print(f"\n--- TEST AlternativeDataSensor ({test_ticker}) ---")
    print(AlternativeDataSensor.extract(test_ticker))

    print(f"\n--- TEST LegalSensor ({test_ticker}) ---")
    print(LegalSensor.extract(test_ticker))
