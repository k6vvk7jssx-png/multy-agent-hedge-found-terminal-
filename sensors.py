import json
import time
import random
import logging
import os
import re
from pathlib import Path
from bs4 import BeautifulSoup
import yfinance as yf
from sec_edgar_downloader import Downloader
from mcp_bridge import mcp_brave_search

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"QuantSensor: Errore salvataggio cache {ticker_symbol}: {e}")

    @staticmethod
    def extract(ticker_symbol: str) -> str:
        """
        Estrae metriche fondamentali complete da yfinance:
        - Valutazione: P/E, EV/EBITDA, P/S, P/B
        - Profittabilità: EBITDA, Margini Lordi/Operativi/Netti, ROE, ROA, ROIC
        - Liquidità e Debito: Debt/Equity, Current Ratio, Free Cash Flow
        - Income Statement (3 anni), Cash Flow Statement (3 anni)
        - Bilancio Patrimoniale (Balance Sheet, 3 anni)
        - Surprise sugli utili trimestrali (EPS Actual vs Estimated)
        - Prossimi eventi (Earnings Date, Dividendi)
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
                """Converte un DataFrame yfinance in dizionario JSON-safe (ultimi N anni/trimestri)."""
                if df is None or df.empty:
                    return {}
                sliced = df.iloc[:, :cols].copy()
                sliced.columns = [str(c).split(" ")[0] for c in sliced.columns]
                return sliced.fillna("N/A").to_dict()

            # --- INCOME STATEMENT (3 anni annuali) ---
            income_annual = df_to_dict(stock.income_stmt, 3)

            # --- CASH FLOW STATEMENT (3 anni annuali) ---
            cashflow_annual = df_to_dict(stock.cashflow, 3)

            # --- BALANCE SHEET (3 anni annuali) ---
            balance_annual = df_to_dict(stock.balance_sheet, 3)

            # --- EARNINGS HISTORY (Surprise EPS trimestrali) ---
            earnings_hist = {}
            try:
                eh = stock.earnings_history
                if eh is not None and not eh.empty:
                    eh_clean = eh.tail(8).copy()  # Ultimi 8 trimestri
                    eh_clean.index = [str(i).split(" ")[0] for i in eh_clean.index]
                    earnings_hist = eh_clean[[c for c in ["epsEstimate", "epsActual", "surprisePercent"] if c in eh_clean.columns]].fillna("N/A").to_dict()
            except Exception as e:
                logger.warning(f"QuantSensor: Earnings history non disponibile per {ticker_symbol}: {e}")

            # --- PROSSIMI EVENTI (Calendar) ---
            calendar_data = {}
            try:
                cal = stock.calendar
                if cal:
                    # cal può essere un dict o un DataFrame a seconda della versione yfinance
                    if hasattr(cal, 'to_dict'):
                        calendar_data = {k: str(v) for k, v in cal.to_dict().items()}
                    elif isinstance(cal, dict):
                        calendar_data = {k: str(v) for k, v in cal.items()}
            except Exception as e:
                logger.warning(f"QuantSensor: Calendar non disponibile per {ticker_symbol}: {e}")

            result["data"] = {
                # --- VALUTAZIONE ---
                "trailingPE":        info.get("trailingPE"),
                "forwardPE":         info.get("forwardPE"),
                "priceToSales":      info.get("priceToSalesTrailing12Months"),
                "priceToBook":       info.get("priceToBook"),
                "enterpriseToEbitda": info.get("enterpriseToEbitda"),
                "enterpriseValue":   info.get("enterpriseValue"),
                "marketCap":         info.get("marketCap"),

                # --- PROFITTABILITÀ ---
                "ebitda":            info.get("ebitda"),
                "grossMargins":      info.get("grossMargins"),
                "operatingMargins":  info.get("operatingMargins"),
                "profitMargins":     info.get("profitMargins"),
                "returnOnEquity":    info.get("returnOnEquity"),
                "returnOnAssets":    info.get("returnOnAssets"),

                # --- LIQUIDITÀ E DEBITO ---
                "totalDebt":         info.get("totalDebt"),
                "totalCash":         info.get("totalCash"),
                "debtToEquity":      info.get("debtToEquity"),
                "currentRatio":      info.get("currentRatio"),
                "quickRatio":        info.get("quickRatio"),
                "freeCashflow":      info.get("freeCashflow"),
                "operatingCashflow": info.get("operatingCashflow"),

                # --- CRESCITA ---
                "revenueGrowth":     info.get("revenueGrowth"),
                "earningsGrowth":    info.get("earningsGrowth"),
                "earningsQuarterlyGrowth": info.get("earningsQuarterlyGrowth"),

                # --- BILANCI COMPLETI ---
                "income_stmt_annual":   income_annual,
                "cashflow_annual":      cashflow_annual,
                "balance_sheet_annual": balance_annual,

                # --- EARNINGS SURPRISE STORIA ---
                "earnings_history":  earnings_hist,

                # --- PROSSIMI EVENTI ---
                "calendar":          calendar_data,
            }
            result["success"] = True
            QuantSensor.save_to_cache(ticker_symbol, result)

        except Exception as e:
            logger.error(f"QuantSensor: Errore estrazione {ticker_symbol}: {str(e)}")
            result["error"] = str(e)

        finally:
            sleep_time = random.uniform(3.0, 6.0)
            logger.info(f"QuantSensor: Pausa anti-ban di {sleep_time:.2f}s...")
            time.sleep(sleep_time)

        return json.dumps(result, indent=2, ensure_ascii=False)


class LegalSensor:
    SEC_DOWNLOAD_DIR = "sec_filings"
    USER_AGENT_COMPANY = "HedgeFund"
    USER_AGENT_EMAIL = "admin@local.dev"
    MAX_TEXT_LENGTH = 8000

    @staticmethod
    def extract(ticker: str) -> str:
        """
        Scarica l'ultimo Form 10-K tramite sec-edgar-downloader e analizza l'HTML
        con BeautifulSoup per estrarre Item 1A (Risk Factors) e Item 3 (Legal Proceedings).
        Restituisce JSON.
        """
        result = {"ticker": ticker, "success": False, "data": {}, "error": None}
        
        try:
            logger.info(f"LegalSensor: Avvio download 10-K per {ticker}...")
            dl = Downloader(LegalSensor.USER_AGENT_COMPANY, LegalSensor.USER_AGENT_EMAIL, LegalSensor.SEC_DOWNLOAD_DIR)
            num_downloaded = dl.get("10-K", ticker, limit=1)
            
            if num_downloaded == 0:
                result["error"] = "Nessun Form 10-K trovato per il ticker."
                return json.dumps(result, indent=2, ensure_ascii=False)
                
            base_path = Path(LegalSensor.SEC_DOWNLOAD_DIR) / "sec-edgar-filings" / ticker / "10-K"
            html_files = list(base_path.rglob("*.html")) + list(base_path.rglob("*.txt"))
            
            if not html_files:
                raise FileNotFoundError("Download segnalato con successo, ma file non trovati su disco.")
                
            primary_file = html_files[0]
            logger.info(f"LegalSensor: Parsing documento {primary_file}...")
            
            with open(primary_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            soup = BeautifulSoup(content, 'html.parser')
            text_content = soup.get_text(separator=' ', strip=True)
            
            # Euristica di estrazione (Item 1A e Item 3)
            item_1a_match = re.search(r'(?i)item\s+1a\.?\s+risk\s+factors(.*?)(?:item\s+1b|item\s+2)', text_content, re.DOTALL)
            item_3_match = re.search(r'(?i)item\s+3\.?\s+legal\s+proceedings(.*?)(?:item\s+4)', text_content, re.DOTALL)
            
            risk_factors = item_1a_match.group(1).strip() if item_1a_match else "Sezione Risk Factors non individuata chiaramente."
            legal_proceedings = item_3_match.group(1).strip() if item_3_match else "Sezione Legal Proceedings non individuata chiaramente."
            
            # Fallback se le euristiche non portano a risultati validi (molto comune con i SEC filings formattati male)
            if len(risk_factors) < 100 and len(legal_proceedings) < 100:
                logger.warning(f"LegalSensor: Sezioni non trovate. Utilizzo fallback troncato a {LegalSensor.MAX_TEXT_LENGTH} caratteri.")
                fallback_text = text_content[:LegalSensor.MAX_TEXT_LENGTH]
                result["data"] = {
                    "risk_factors": "Fallback attivato",
                    "legal_proceedings": "Fallback attivato",
                    "raw_fallback": fallback_text
                }
            else:
                result["data"] = {
                    "risk_factors": risk_factors[:LegalSensor.MAX_TEXT_LENGTH],
                    "legal_proceedings": legal_proceedings[:LegalSensor.MAX_TEXT_LENGTH]
                }
                
            result["success"] = True

        except Exception as e:
            logger.error(f"LegalSensor: Errore fatale per {ticker}: {str(e)}")
            result["error"] = str(e)
            
        return json.dumps(result, indent=2, ensure_ascii=False)


class QuarterlySensor:
    """
    Scarica e analizza il Form 10-Q (Comunicato Trimestrale SEC) per aziende USA.
    Estrae Management Discussion & Analysis (MD&A, Item 2) e Risk Updates (Item 1A).
    """
    SEC_DOWNLOAD_DIR = "sec_filings"
    USER_AGENT_COMPANY = "HedgeFund"
    USER_AGENT_EMAIL = "admin@local.dev"
    MAX_TEXT_LENGTH = 6000

    @staticmethod
    def extract(ticker: str) -> str:
        """
        Scarica l'ultimo Form 10-Q dalla SEC e ne estrae i contenuti chiave:
        - Item 2: Management's Discussion & Analysis (MD&A) — il cuore del comunicato trimestrale
        - Item 1A: Risk Factors aggiornati (se presenti nel trimestrale)
        """
        result = {"ticker": ticker, "success": False, "data": {}, "error": None}

        try:
            logger.info(f"QuarterlySensor: Avvio download ultimo 10-Q per {ticker}...")
            dl = Downloader(
                QuarterlySensor.USER_AGENT_COMPANY,
                QuarterlySensor.USER_AGENT_EMAIL,
                QuarterlySensor.SEC_DOWNLOAD_DIR
            )
            num_downloaded = dl.get("10-Q", ticker, limit=1)

            if num_downloaded == 0:
                result["error"] = "Nessun Form 10-Q trovato. L'azienda potrebbe non essere quotata USA o non aver ancora depositato il trimestrale."
                return json.dumps(result, indent=2, ensure_ascii=False)

            base_path = Path(QuarterlySensor.SEC_DOWNLOAD_DIR) / "sec-edgar-filings" / ticker / "10-Q"
            html_files = list(base_path.rglob("*.html")) + list(base_path.rglob("*.htm")) + list(base_path.rglob("*.txt"))

            if not html_files:
                raise FileNotFoundError("10-Q scaricato ma file non trovati su disco.")

            # Ordina per data modifica (il più recente è il 10-Q più fresco)
            html_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            primary_file = html_files[0]
            logger.info(f"QuarterlySensor: Parsing {primary_file.name}...")

            with open(primary_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            soup = BeautifulSoup(content, 'html.parser')
            text_content = soup.get_text(separator=' ', strip=True)

            # Item 2: MD&A — il comunicato gestionale trimestrale più importante
            mda_match = re.search(
                r'(?i)item\s+2\.?\s+management.{0,30}discussion(.*?)(?:item\s+3|item\s+4)',
                text_content, re.DOTALL
            )
            # Item 1A: Risk Factors aggiornati nel trimestrale
            risk_match = re.search(
                r'(?i)item\s+1a\.?\s+risk\s+factors(.*?)(?:item\s+1b|item\s+2|item\s+3)',
                text_content, re.DOTALL
            )

            mda_text = mda_match.group(1).strip() if mda_match else "Sezione MD&A non localizzata nel documento."
            risk_text = risk_match.group(1).strip() if risk_match else "Nessun aggiornamento Risk Factors nel 10-Q corrente."

            result["data"] = {
                "form_type": "10-Q",
                "source_file": str(primary_file),
                "mda_management_discussion": mda_text[:QuarterlySensor.MAX_TEXT_LENGTH],
                "risk_factors_update": risk_text[:QuarterlySensor.MAX_TEXT_LENGTH],
            }
            result["success"] = True
            logger.info(f"QuarterlySensor: Estrazione 10-Q completata per {ticker}.")

        except Exception as e:
            logger.error(f"QuarterlySensor: Errore fatale per {ticker}: {str(e)}")
            result["error"] = str(e)

        return json.dumps(result, indent=2, ensure_ascii=False)




class AlternativeDataSensor:
    """
    Sfrutta il protocollo MCP (Model Context Protocol) collegato a Brave Search
    per estrarre in tempo reale dati non strutturati, sentiment da Twitter/X e Reddit (WallStreetBets).
    """
    @staticmethod
    def extract(ticker: str) -> str:
        logger.info(f"AltDataSensor: Interrogazione MCP Server (Brave Search) per {ticker}...")
        
        # Query 1: Twitter/X sentiment
        query_twitter = f"site:twitter.com OR site:x.com {ticker} stock market sentiment opinion"
        twitter_res = mcp_brave_search(query_twitter)
        
        # Query 2: Reddit WallStreetBets sentiment
        query_reddit = f"site:reddit.com/r/wallstreetbets {ticker} sentiment analysis"
        reddit_res = mcp_brave_search(query_reddit)
        
        result = {
            "ticker": ticker,
            "success": True,
            "data": {
                "twitter_sentiment_search": twitter_res,
                "reddit_sentiment_search": reddit_res
            }
        }
        
        if "ERROR:" in twitter_res or "ERROR:" in reddit_res:
            result["success"] = False
            result["error"] = "Problemi di connessione con il Server MCP o API Key mancante."
            
        return json.dumps(result, indent=2, ensure_ascii=False)


class InsiderSensor:
    """
    Estrae dati sui movimenti dei capitali interni (Insider Trading) 
    e sulla struttura proprietaria (Institutional Holders).
    """
    @staticmethod
    def extract(ticker_symbol: str) -> str:
        logger.info(f"InsiderSensor: Estrazione dati Insider e Ownership per {ticker_symbol}...")
        result = {"ticker": ticker_symbol, "success": False, "data": {}, "error": None}
        
        try:
            stock = yf.Ticker(ticker_symbol)
            
            # 1. Insider Transactions (Acquisti/Vendite recenti)
            insider_trans = {}
            try:
                df_it = stock.insider_transactions
                if df_it is not None and not df_it.empty:
                    # Prendiamo le ultime 15 transazioni significativi
                    df_it_clean = df_it.head(15).copy()
                    df_it_clean['Start Date'] = df_it_clean.index.astype(str)
                    insider_trans = df_it_clean.fillna("N/A").to_dict(orient='records')
            except Exception as e:
                logger.warning(f"InsiderSensor: Insider transactions non disponibili: {e}")

            # 2. Institutional Holders (Chi possiede l'azienda)
            inst_holders = {}
            try:
                df_ih = stock.institutional_holders
                if df_ih is not None and not df_ih.empty:
                    inst_holders = df_ih.fillna("N/A").to_dict(orient='records')
            except Exception as e:
                logger.warning(f"InsiderSensor: Institutional holders non disponibili: {e}")

            # 3. Short Interest e Float (Sentiment contro il titolo)
            info = stock.info
            short_data = {
                "shortPercentOfFloat": info.get("shortPercentOfFloat"),
                "shortRatio": info.get("shortRatio"),
                "sharesShort": info.get("sharesShort"),
                "sharesShortPriorMonth": info.get("sharesShortPriorMonth")
            }

            result["data"] = {
                "insider_transactions": insider_trans,
                "institutional_holders": inst_holders,
                "short_interest": short_data
            }
            result["success"] = True

        except Exception as e:
            logger.error(f"InsiderSensor: Errore fatale per {ticker_symbol}: {str(e)}")
            result["error"] = str(e)
            
        return json.dumps(result, indent=2, ensure_ascii=False)


    # Routine di testing per esecuzione standalone


    test_ticker = 'AAPL'
    print(f"\n--- TEST QuantSensor ({test_ticker}) ---")
    quant_res = QuantSensor.extract(test_ticker)
    print(quant_res)
    
    print(f"\n--- TEST LegalSensor ({test_ticker}) ---")
    legal_res = LegalSensor.extract(test_ticker)
    print(legal_res)
