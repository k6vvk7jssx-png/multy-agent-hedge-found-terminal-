import json
import logging
import os
from pathlib import Path
from sec_edgar_downloader import Downloader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configurazione Costanti (da migrare poi in variabili d'ambiente)
SEC_DOWNLOAD_DIR = "sec_filings"
USER_AGENT_COMPANY = "HedgeFund_Core"
USER_AGENT_EMAIL = "admin@local.dev"

def download_10k(ticker: str) -> str:
    """
    Scarica l'ultimo Form 10-K del ticker specificato usando sec-edgar-downloader.
    Ricerca il path del file scaricato e restituisce un payload JSON strutturato
    per essere consumato in modo sicuro dagli step successivi della pipeline (es. LLM).
    """
    result = {
        "ticker": ticker,
        "success": False,
        "data": {},
        "error": None
    }
    
    try:
        logger.info(f"Avvio download dell'ultimo 10-K per {ticker}...")
        
        # Inizializza il downloader con l'User-Agent istituzionale richiesto
        dl = Downloader(USER_AGENT_COMPANY, USER_AGENT_EMAIL, SEC_DOWNLOAD_DIR)
        
        # Scarica l'ultimo (limit=1) Form 10-K per il ticker
        num_downloaded = dl.get("10-K", ticker, limit=1)
        
        if num_downloaded == 0:
            result["error"] = "Nessun Form 10-K trovato per il ticker specificato o blocco SEC attivo."
            return json.dumps(result, indent=2, ensure_ascii=False)
            
        logger.info(f"Download completato. {num_downloaded} documento/i scaricato/i per {ticker}.")
        
        # sec-edgar-downloader salva i file nidificandoli:
        # sec_filings/sec-edgar-filings/<TICKER>/10-K/<ACCESSION_NUMBER>/
        # Navighiamo l'albero per estrarre i path assoluti dei file HTML/TXT da passare all'LLM.
        base_path = Path(SEC_DOWNLOAD_DIR) / "sec-edgar-filings" / ticker / "10-K"
        
        downloaded_files = []
        if base_path.exists():
            for file_path in base_path.rglob("*.*"):
                # Filtriamo solo per documenti testuali/html
                if file_path.suffix in ['.html', '.txt']:
                    # Convertiamo in path assoluto e standardizzato (usando forward slash)
                    downloaded_files.append(str(file_path.absolute().as_posix()))
                    
        if not downloaded_files:
            raise FileNotFoundError("Download segnalato con successo, ma file non trovati su disco.")

        result["success"] = True
        result["data"] = {
            "download_count": num_downloaded,
            "primary_file": downloaded_files[0] if downloaded_files else None,
            "all_files": downloaded_files
        }

    except ConnectionError as ce:
        logger.error(f"Network Timeout/Connection Refused da SEC.gov: {ce}")
        result["error"] = f"Network Error: {str(ce)}"
    except PermissionError as pe:
        logger.error(f"Errore di permessi I/O su disco nella cartella {SEC_DOWNLOAD_DIR}: {pe}")
        result["error"] = f"IO Permission Error: {str(pe)}"
    except Exception as e:
        logger.error(f"Eccezione non gestita durante l'estrazione SEC per {ticker}: {str(e)}")
        result["error"] = f"Fatal Error: {str(e)}"
        
    return json.dumps(result, indent=2, ensure_ascii=False)

if __name__ == '__main__':
    # Testare il codice sul ticker 'AAPL'
    output = download_10k('AAPL')
    print(output)
