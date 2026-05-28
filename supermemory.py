import logging
import time
import chromadb
from chromadb.utils import embedding_functions

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SuperMemory:
    def __init__(self, db_path: str = "./chroma_db", collection_name: str = "due_diligence_vault"):
        try:
            logger.info(f"SuperMemory: Inizializzazione ChromaDB PersistentClient su '{db_path}'...")
            self.client = chromadb.PersistentClient(path=db_path)
            
            # Utilizziamo l'embedding function di default (all-MiniLM-L6-v2) 
            # che opera in locale senza chiamate API esterne, ottimo per lo stealth e la velocità.
            self.ef = embedding_functions.DefaultEmbeddingFunction()
            
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.ef,
                metadata={"description": "Vault vettoriale per report finanziari e legali"}
            )
            logger.info(f"SuperMemory: Collezione '{collection_name}' pronta. Vettori attuali: {self.collection.count()}")
        except Exception as e:
            logger.error(f"SuperMemory: Errore critico in inizializzazione ChromaDB: {e}")
            raise

    def ingest_data(self, ticker: str, raw_text: str) -> bool:
        """
        Salva i dati estratti nel database vettoriale per interrogazioni future.
        """
        if not raw_text or len(raw_text.strip()) == 0:
            logger.warning(f"SuperMemory: Testo vuoto per {ticker}, skip ingestione.")
            return False
            
        try:
            timestamp = int(time.time())
            doc_id = f"{ticker}_{timestamp}"
            
            # Metadata per permettere filtri successivi incrociati
            metadata = {
                "ticker": ticker,
                "timestamp": timestamp,
                "source": "automated_due_diligence"
            }
            
            self.collection.add(
                documents=[raw_text],
                metadatas=[metadata],
                ids=[doc_id]
            )
            
            logger.info(f"SuperMemory: Ingestione completata per {ticker} (ID Documento: {doc_id}).")
            return True
            
        except Exception as e:
            logger.error(f"SuperMemory: Errore durante l'ingestione vettoriale per {ticker}: {e}")
            return False

    def query_context(self, query_string: str, n_results: int = 3) -> list:
        """
        Recupera semanticamente i contesti storici e le anomalie simili dal database locale.
        """
        if self.collection.count() == 0:
            logger.warning("SuperMemory: Database vuoto. Nessun contesto storico disponibile.")
            return []
            
        try:
            logger.info(f"SuperMemory: Ricerca semantica per: '{query_string}' (Richiesti Top {n_results})")
            
            # Limitiamo n_results al massimo numero di documenti per evitare eccezioni
            safe_n_results = min(n_results, self.collection.count())
            
            results = self.collection.query(
                query_texts=[query_string],
                n_results=safe_n_results
            )
            
            # I risultati di ChromaDB sono array annidati
            if results and results.get("documents") and len(results["documents"]) > 0:
                docs = results["documents"][0]
                metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
                
                formatted_results = []
                for doc, meta in zip(docs, metadatas):
                    formatted_results.append({
                        "content": doc,
                        "metadata": meta
                    })
                return formatted_results
            return []
            
        except Exception as e:
            logger.error(f"SuperMemory: Errore durante la query su ChromaDB: {e}")
            return []


if __name__ == "__main__":
    # Routine di testing per esecuzione standalone
    print("--- Avvio Test SuperMemory ---")
    memory = SuperMemory()
    
    test_ticker = "TEST_INC"
    test_payload = "L'azienda affronta sfide sistemiche legate alla supply chain e rischia azioni legali per brevetti."
    
    print(f"\n1. Ingestione Dati per {test_ticker}...")
    success = memory.ingest_data(test_ticker, test_payload)
    print(f"Risultato Ingestione: {'Completata' if success else 'Fallita'}")
    
    print("\n2. Recupero Semantico...")
    query = "ci sono aziende con problemi di supply chain e legali?"
    res = memory.query_context(query)
    
    print("\nRisultati della query:")
    for idx, r in enumerate(res):
        print(f"{idx+1}. [Ticker: {r['metadata'].get('ticker')}] -> {r['content']}")
