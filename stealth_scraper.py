import json
import time
import random
import logging
import os
from pathlib import Path

import yfinance as yf
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600  # Un'ora in secondi

def get_from_cache(ticker_symbol: str) -> dict:
    """Controlla se esiste una cache valida (creata da meno di un'ora) per il ticker."""
    cache_file = Path(f"cache_{ticker_symbol}.json")
    if cache_file.exists():
        file_age = time.time() - cache_file.stat().st_mtime
        if file_age < CACHE_TTL_SECONDS:
            logger.info(f"Cache valida trovata per {ticker_symbol} (età: {int(file_age)}s). Skippo la chiamata web.")
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Impossibile leggere la cache per {ticker_symbol}: {e}")
    return None

def save_to_cache(ticker_symbol: str, data: dict):
    """Salva il JSON estratto in locale per i futuri utilizzi."""
    cache_file = Path(f"cache_{ticker_symbol}.json")
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Dati salvati con successo nel file {cache_file}.")
    except Exception as e:
        logger.warning(f"Errore durante il salvataggio della cache per {ticker_symbol}: {e}")

def extract_financial_data(ticker_symbol: str) -> str:
    """
    Estrae dati finanziari e l'income statement da Yahoo Finance,
    utilizzando un sistema di caching locale su file system per simulare
    un rate limiting e ottimizzare le chiamate.
    Ritorna JSON puro e gestisce eccezioni.
    """
    # 1. Controllo cache locale prima di fare la chiamata web
    cached_data = get_from_cache(ticker_symbol)
    if cached_data:
        return json.dumps(cached_data, indent=2, ensure_ascii=False)

    # 2. Cache non valida o inesistente: setup base
    result = {
        "ticker": ticker_symbol,
        "success": False,
        "data": {},
        "error": None
    }
    
    try:
        logger.info(f"Avvio estrazione da Yahoo Finance per {ticker_symbol}...")
        
        # Chiamata yfinance standard come richiesto (bypass curl_cffi bug)
        stock = yf.Ticker(ticker_symbol)
        
        info = stock.info
        
        # Estrai: Trailing P/E, Forward P/E, Market Cap, Margini Operativi, ROE
        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        market_cap = info.get("marketCap")
        operating_margins = info.get("operatingMargins")
        roe = info.get("returnOnEquity")
        
        # Estrai la tabella income_stmt ma tagliala per mostrare solo gli ultimi 3 anni
        income_stmt_df = stock.income_stmt
        
        if income_stmt_df is not None and not income_stmt_df.empty:
            # Gli ultimi 3 anni sono le prime 3 colonne in yfinance
            income_stmt_recent = income_stmt_df.iloc[:, :3].copy()
            # Converti gli headers datetime in formato stringa per il JSON
            income_stmt_recent.columns = [str(col).split(' ')[0] for col in income_stmt_recent.columns]
            # Sostituisci i NaN di pandas con "N/A"
            income_stmt_dict = income_stmt_recent.fillna("N/A").to_dict()
        else:
            income_stmt_dict = {}

        result["data"] = {
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "market_cap": market_cap,
            "operating_margins": operating_margins,
            "roe": roe,
            "income_stmt_last_3_years": income_stmt_dict
        }
        result["success"] = True

        # Salva il nuovo JSON estratto in locale
        save_to_cache(ticker_symbol, result)

    except Exception as e:
        logger.error(f"Errore critico durante l'estrazione per {ticker_symbol}: {str(e)}")
        result["error"] = str(e)
    
    finally:
        # Inserisci time.sleep casuale tra 3 e 6 secondi per simulare rate-limiting umano
        sleep_time = random.uniform(3.0, 6.0)
        logger.info(f"Stealth delay: attesa di {sleep_time:.2f} secondi...")
        time.sleep(sleep_time)
        
    # Formatta il risultato in JSON puro
    return json.dumps(result, indent=2, ensure_ascii=False)

if __name__ == '__main__':
    # Testare il codice sul ticker 'AAPL' e stampare l'output
    output = extract_financial_data('AAPL')
    print(output)
