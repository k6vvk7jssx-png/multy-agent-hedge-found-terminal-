import os
import sys
import io

# Fix per Windows: Forza UTF-8 per supportare le emoji di CrewAI ed evitare crash su 'charmap'
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import json
import logging
import datetime
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool

# Importazione dei sensori dati
from sensors import QuantSensor, LegalSensor, QuarterlySensor, AlternativeDataSensor, InsiderSensor
from supermemory import SuperMemory

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# LLM DeepSeek-V3 (Standard per analisti)
deepseek_llm = LLM(
    model="deepseek/deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# LLM DeepSeek-R1 (Ragionamento per il CIO)
deepseek_r1_llm = LLM(
    model="deepseek/deepseek-reasoner",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# Inizializzazione lazy per evitare importazioni lente all'avvio dell'app Streamlit
_memory = None

def get_memory():
    """Inizializzazione pigra (lazy) di SuperMemory."""
    global _memory
    if _memory is None:
        try:
            logger.info("Orchestrator: Inizializzazione lazy di SuperMemory (ChromaDB)...")
            _memory = SuperMemory()
        except Exception as e:
            logger.error(f"Orchestrator: Errore inizializzazione lazy SuperMemory: {e}")
            _memory = None
    return _memory


# ==========================================
# TOOLS PER GLI AGENTI CREWAI
# ==========================================

@tool("Get Quantitative Data")
def get_quant_data(ticker: str) -> str:
    """
    Extracts all key financial fundamentals for a stock ticker:
    valuation multiples (P/E, EV/EBITDA, P/S, P/B), profitability margins,
    ROE, ROA, free cash flow, debt levels, 3-year financial statements,
    EPS surprise history, next earnings date, and recent news headlines.
    Use this to assess whether the stock is cheap or expensive, 
    whether the business is growing or deteriorating, and what the market currently thinks.
    """
    return QuantSensor.extract(ticker)


@tool("Get Legal and Risk Data")
def get_legal_data(ticker: str) -> str:
    """
    Extracts legal risks, lawsuits, and risk factor disclosures from the SEC 10-K annual filing.
    Falls back to Google News RSS search if SEC is unavailable (e.g. for non-US tickers).
    Use this to identify hidden legal landmines, regulatory threats, or systemic risks
    that could destroy equity value or create liability overhangs.
    """
    return LegalSensor.extract(ticker)


@tool("Get Quarterly Earnings Narrative")
def get_quarterly_data(ticker: str) -> str:
    """
    Downloads the latest SEC 10-Q quarterly filing and extracts Management Discussion & Analysis (MD&A).
    Falls back to Google News RSS + Yahoo Finance news if SEC is unavailable.
    Use this to understand what management said about the quarter, 
    whether revenue growth is accelerating or decelerating, 
    and if there are any early warning signals about future performance.
    """
    return QuarterlySensor.extract(ticker)


@tool("Get News and Sentiment Data")
def get_alt_data(ticker: str) -> str:
    """
    Retrieves real-time news sentiment and retail investor opinion from 
    Yahoo Finance and Google News RSS. No API key required.
    Use this to gauge whether the market mood is bullish or bearish,
    whether there is unusual hype or fear around the stock, 
    and what the latest narrative in the media is.
    """
    return AlternativeDataSensor.extract(ticker)


@tool("Get Insider and Ownership Data")
def get_insider_data(ticker: str) -> str:
    """
    Extracts insider transactions (executive buys/sells), top institutional holders,
    and short interest data.
    Use this to understand if the 'smart money' is entering or exiting,
    if executives are selling in large quantities (bearish signal), 
    and if high short interest indicates institutional skepticism or short squeeze potential.
    """
    return InsiderSensor.extract(ticker)


@tool("Search Historical Context")
def search_historical_context(query: str) -> str:
    """
    Searches the local ChromaDB vector database for historically similar investment cases,
    past legal risks, or structural patterns that match the current analysis query.
    Use this to find precedents: e.g. 'has high debt and slowing growth in the same sector led to crashes before?'
    """
    memory = get_memory()
    if memory is None:
        return json.dumps({"error": "Vector database unavailable."})
    results = memory.query_context(query, n_results=3)
    return json.dumps(results, indent=2, ensure_ascii=False)


# ==========================================
# PIPELINE DI AGENTI
# ==========================================

def run_due_diligence(ticker: str, step_callback=None, api_key: str = None) -> str:
    today = datetime.datetime.now().strftime("%A %d %B %Y")
    logger.info(f"Avvio pipeline 6-agenti per: {ticker.upper()} — {today}")

    active_key = api_key if api_key else os.getenv("DEEPSEEK_API_KEY")
    
    # LLM per gli analisti (DeepSeek-V3, veloce e strutturato)
    active_v3_llm = LLM(
        model="deepseek/deepseek-chat",
        api_key=active_key,
        base_url="https://api.deepseek.com"
    ) if active_key else deepseek_llm

    # LLM per il CIO (DeepSeek-R1, ragionamento profondo)
    active_r1_llm = LLM(
        model="deepseek/deepseek-reasoner",
        api_key=active_key,
        base_url="https://api.deepseek.com"
    ) if active_key else deepseek_r1_llm

    # ------------------------------------------------------------------
    # AGENTE 1: ANALISTA QUANTITATIVO
    # Obiettivo: spiegare PERCHÉ i numeri sono positivi o negativi
    # ------------------------------------------------------------------
    quant_analyst = Agent(
        role='Senior Quantitative Analyst',
        goal=(
            f"DATA ODIERNA: {today}. "
            "Analizza i fondamentali di {ticker}. "
            "NON limitarti a elencare i numeri: spiega COSA SIGNIFICANO per l'investitore. "
            "Esempio: 'Il P/E di 35x rispetto alla media del settore di 20x implica un premio di valutazione elevato che si giustifica solo se la crescita degli utili accelera nei prossimi 2-3 trimestri.' "
            "Identifica la principale FORZA e la principale DEBOLEZZA numerica. "
            "Scrivi in ITALIANO professionale."
        ),
        backstory=(
            "Sei un analista quantitativo ex-Goldman Sachs. Lavori per un hedge fund attivista. "
            "Hai imparato che i numeri da soli non decidono l'investimento: è la loro DINAMICA e il loro IMPATTO sul flusso di cassa futuro che conta. "
            "Sei conciso, preciso e orientato alla decisione."
        ),
        tools=[get_quant_data],
        llm=active_v3_llm,
        verbose=True,
        step_callback=step_callback
    )

    # ------------------------------------------------------------------
    # AGENTE 2: ANALISTA TRIMESTRALI
    # Obiettivo: cosa ha detto il management e cosa nasconde
    # ------------------------------------------------------------------
    quarterly_analyst = Agent(
        role='Quarterly Intelligence Analyst',
        goal=(
            "Leggi il report trimestrale (10-Q o notizie equivalenti) e rispondi: "
            "1. La crescita dei ricavi sta accelerando o decelerando? "
            "2. Il management ha alzato, abbassato o mantenuto la guidance? "
            "3. Ci sono segnali di deterioramento operativo nascosti nel linguaggio vago? "
            "4. Qual è il singolo dato più importante per decidere se comprare o vendere ora? "
            "Scrivi in ITALIANO professionale."
        ),
        backstory=(
            "Sei specializzato nell'analisi forense dei comunicati trimestrali. "
            "Sai che le aziende usano frasi come 'sfide macroeconomiche' per nascondere perdite di quote di mercato. "
            "Sei diretto e non ti fai ingannare dal gergo aziendale."
        ),
        tools=[get_quarterly_data],
        llm=active_v3_llm,
        verbose=True,
        step_callback=step_callback
    )

    # ------------------------------------------------------------------
    # AGENTE 3: AUDITOR FORENSE
    # Obiettivo: rischi legali e il loro impatto reale sul business
    # ------------------------------------------------------------------
    forensic_auditor = Agent(
        role='Forensic Legal Auditor',
        goal=(
            "Analizza i rischi legali del 10-K (o delle notizie di fallback). "
            "NON elencare i rischi standard: identifica quelli che potrebbero DISTRUGGERE il valore azionario. "
            "Spiega: se questo rischio si materializza, quanto impatta sul prezzo? "
            "Cerca precedenti storici nel database per capire se rischi simili si sono già tradotti in crolli. "
            "Scrivi in ITALIANO professionale."
        ),
        backstory=(
            "Sei un ex-regolatore SEC. Hai visto decine di aziende nascondere rischi catastrofici nel linguaggio burocratico dei Risk Factors. "
            "Sai distinguere il rischio boilerplate (che tutte le aziende copiano) dal rischio materiale che può far crollare il titolo del 50%."
        ),
        tools=[get_legal_data, search_historical_context],
        llm=active_v3_llm,
        verbose=True,
        step_callback=step_callback
    )

    # ------------------------------------------------------------------
    # AGENTE 4: SENTIMENT ANALYST
    # Obiettivo: cosa pensa il mercato e la community retail ADESSO
    # ------------------------------------------------------------------
    alt_data_analyst = Agent(
        role='News & Market Sentiment Analyst',
        goal=(
            "Analizza le notizie recenti e il sentiment di mercato. "
            "Rispondi: il mercato è più ottimista o pessimista rispetto a 30 giorni fa? "
            "Ci sono catalizzatori imminenti (FDA, earnings, acquisizioni, regulatory) che possono muovere il titolo? "
            "Il sentiment retail (Reddit, Twitter) è in linea con quello istituzionale o c'è una discrepanza? "
            "Scrivi in ITALIANO professionale."
        ),
        backstory=(
            "Sei uno specialista dei mercati moderni. Sai che in un mondo di information overload, "
            "ciò che muove i prezzi nel breve termine è la NARRATIVA, non i fondamentali. "
            "Il tuo compito è identificare la narrativa dominante e capire se sta per cambiare."
        ),
        tools=[get_alt_data],
        llm=active_v3_llm,
        verbose=True,
        step_callback=step_callback
    )

    # ------------------------------------------------------------------
    # AGENTE 5: INSIDER ANALYST
    # Obiettivo: dove sta andando il 'smart money'
    # ------------------------------------------------------------------
    insider_analyst = Agent(
        role='Insider Flow & Capital Intelligence Analyst',
        goal=(
            "Analizza le transazioni insider e la struttura proprietaria. "
            "Rispondi direttamente: i CEO/CFO stanno comprando o vendendo? "
            "Gli istituzionali stanno accumulando o distribuendo? "
            "Lo short interest è alto e in aumento (segnale di sfiducia istituzionale) o basso (mercato fiducioso)? "
            "Qual è la tua lettura complessiva dei flussi di capitale intelligente? "
            "Scrivi in ITALIANO professionale."
        ),
        backstory=(
            "Sei un detective dei flussi di capitale. "
            "Sai che i CEO vendono per mille ragioni (tasse, divorzi, diversificazione), "
            "ma comprano solo per una: credono che il prezzo salirà. "
            "Le vendite massive di più insider contemporaneamente sono sempre un segnale da non ignorare."
        ),
        tools=[get_insider_data],
        llm=active_v3_llm,
        verbose=True,
        step_callback=step_callback
    )

    # ------------------------------------------------------------------
    # AGENTE 6: CIO / EXECUTIONER
    # Obiettivo: verdetto finale chiaro e azionabile
    # ------------------------------------------------------------------
    executioner = Agent(
        role='Chief Investment Officer (The Executioner)',
        goal=(
            "Sintetizza ed elabora TUTTE le analisi degli agenti in un dossier di investimento strategico e approfondito in ITALIANO. "
            "Il report non deve essere una sintesi generica o troppo breve: deve essere specifico, ricco di dati e dettagli operativi concreti. "
            "Fornisci raccomandazioni d'investimento dirette, tesi operative chiare, e consigli tattici precisi su come muoversi sul mercato per capitalizzare sull'asimmetria informativa."
        ),
        backstory=(
            "Sei il CIO di un hedge fund top-tier. "
            "Hai letto migliaia di analisi e sai che quelle inutili sono piene di dati ma prive di giudizio. "
            "Tu produci verdetti netti: LONG, SHORT o PASS, con motivazione chirurgica e rischio/rendimento esplicito. "
            "Non hai paura di sbagliare: hai paura di essere vago."
        ),
        llm=active_r1_llm,
        verbose=True,
        step_callback=step_callback
    )

    # ==========================================
    # TASK DEFINITIONS
    # ==========================================

    quant_task = Task(
        description=(
            f"[DATA: {today}] Estrai e analizza tutti i dati quantitativi e fondamentali per {ticker}. "
            "Usa il tool 'Get Quantitative Data'. "
            "Devi compilare in output le seguenti tabelle in Markdown:\n"
            "1. **Tabella Multipli di Valutazione** con le righe: P/E Trailing, P/E Forward, EV/EBITDA, P/S (Price/Sales), P/B (Price/Book), Enterprise Value. Colonne: Multiplo | Valore | Interpretazione.\n"
            "2. **Trend Margini (ultimi 3 anni)** con le righe: Ricavi Totali, Margine Lordo, Margine Operativo, Margine Netto, EBITDA, Free Cash Flow. Colonne: Metrica | Anno-2 | Anno-1 | Anno Corrente | Trend.\n"
            "3. **Profilo Debito & Struttura Capitale** con le righe: Debito Totale, Cassa Totale, Patrimonio Netto, Azioni in Circolazione, Burn Rate, Autonomia Cassa (in anni). Colonne: Metrica | Valore.\n"
            "4. **Earnings Surprise History (ultimi 4 trimestri)** con le righe: Q1, Q2, Q3, Q4 dell'anno precedente. Colonne: Trimestre | EPS Stimato | EPS Effettivo | Sorpresa.\n"
            "5. **Prossimo Catalizzatore** con le righe degli utili o eventi programmati. Colonne: Evento | Data | Distanza.\n"
            "Successivamente, calcola un `Quantitative Risk Score` (numero da 0 a 100 con giudizio, es. 85.5/100 — RISCHIO ESTREMO) "
            "e formula un `Verdetto Quantitativo` approfondito che spiega l'impatto dei multipli e del flusso di cassa (FCF) sulla sostenibilità aziendale."
        ),
        expected_output=(
            "Report quantitativo in italiano strutturato esattamente con le 5 tabelle Markdown indicate (Multipli, Trend Margini, Struttura Capitale, Surprise History, Catalizzatori), "
            "seguite dal Quantitative Risk Score e dal Verdetto Quantitativo argomentato."
        ),
        agent=quant_analyst
    )

    quarterly_task = Task(
        description=(
            f"[DATA: {today}] Analizza l'ultimo report trimestrale 10-Q (o notizie equivalenti) per {ticker} tramite 'Get Quarterly Earnings Narrative'. "
            "Organizza l'analisi nelle seguenti sezioni:\n"
            "1. **Dichiarazioni Chiave del Management (MD&A)**: Riporta le citazioni letterali più importanti del management suddivise per aree (Sui Ricavi, Sui Costi, Sulla Liquidità, ecc.) "
            "e per ciascuna aggiungi sotto un paragrafo di **Traduzione** in grassetto che esprime la dura realtà dei fatti rispetto al linguaggio aziendale vago o ottimista.\n"
            "2. **Nuovi Rischi Divulgati**: Elenca in forma di bullet point i rischi specifici emersi nell'ultimo trimestre (es. svalutazioni/impairment, rischi diluitivi, fine di sussidi, ecc.).\n"
            "3. **Valutazione Narrativa**: Giudizio riassuntivo (es. ORSO MASSICCIO, TORO fragile, ecc.) con motivazione sintetica."
        ),
        expected_output=(
            "Report trimestrale in italiano che contiene le citazioni letterali del management con la relativa 'Traduzione' critica in grassetto, "
            "la lista dei nuovi rischi e la valutazione narrativa finale."
        ),
        agent=quarterly_analyst
    )

    audit_task = Task(
        description=(
            f"[DATA: {today}] Analizza i rischi legali, normativi e di conformità per {ticker}. "
            "Usa il tool 'Get Legal and Risk Data' e 'Search Historical Context' per interrogare il database dei precedenti. "
            "Devi compilare in output:\n"
            "1. **Matrice delle Bandiere Rosse Forensi**: Tabella con colonne: # | Red Flag | Severità (🔴 CRITICA, 🟠 MATERIALE, ecc.) | Quantum $ (impatto stimato) | Probabilità.\n"
            "2. **Esposizione Legale Stimata**: Tabella con colonne: Categoria | Min | Max | Probabilità (con riga finale del TOTALE stimato).\n"
            "3. **Precedenti Storici**: Cerca nel database vettoriale e indica se ci sono fallimenti o crisi in aziende dello stesso settore per problemi legali o regolamentari simili (es. class action, sanzioni SEC, fallimenti pre-revenue).\n"
            "4. **Forensic Legal Risk Score**: Un punteggio numerico (da 0 a 100 con giudizio, es. 94.1/100 — RISCHIO ESTREMO)."
        ),
        expected_output=(
            "Report forense in italiano contenente la Matrice delle Bandiere Rosse, la tabella dell'Esposizione Legale Stimata, "
            "i paralleli storici emersi dalla ricerca vettoriale, e il Forensic Legal Risk Score finale."
        ),
        agent=forensic_auditor
    )

    alt_data_task = Task(
        description=(
            f"[DATA: {today}] Analizza il sentiment retail, media e istituzionale per {ticker} tramite 'Get News and Sentiment Data'. "
            "Devi compilare in output:\n"
            "1. **Mappa del Sentiment**: Tabella con colonne: Fonte (Twitter/X, Reddit, Istituzionali, Media/Blog, Insider Activity) | Sentimento (🟢 Bullish, 🔴 Bearish, 🟡 Cauto, ecc.) | Trend (30gg) | Confidenza.\n"
            "2. **Rumor Principali in Circolazione**: Tabella con colonne: Rumor | Veridicità (in %) | Impatto (es. Fortemente Bearish, Bullish, ecc.).\n"
            "3. **Sentiment Composito**: Giudizio numerico (es. 24.5/100 — BEARISH) che riflette il passaggio della narrativa."
        ),
        expected_output=(
            "Report sentiment in italiano contenente la tabella Mappa del Sentiment, la tabella dei Rumor in Circolazione, "
            "e il punteggio di Sentiment Composito."
        ),
        agent=alt_data_analyst
    )

    insider_task = Task(
        description=(
            f"[DATA: {today}] Analizza le transazioni dei manager, la diluizione e lo short interest per {ticker} tramite 'Get Insider and Ownership Data'. "
            "Devi compilare in output:\n"
            "1. **Movimenti Insider**: Tabella con colonne: Insider | Ruolo | Transazioni Recenti | Segnale (es. 🔴 Nessun acquisto, 🟢 Accumulo, ecc.).\n"
            "2. **Stock Based Compensation — L'Emorragia**: Tabella con colonne: Anno | SBC | Ricavi | SBC/Ricavi (degli ultimi 3 anni, per valutare la diluizione).\n"
            "3. **Proprietà Istituzionale**: Tabella con colonne: Istituzione | Tipo | Posizione | Segnale.\n"
            "4. **Short Interest**: Tabella con colonne: Metrica | Valore | Interpretazione (includendo Short Interest % Float, Days to Cover, Trend 30gg).\n"
            "5. **Insider & Ownership Score**: Punteggio numerico da 0 a 100."
        ),
        expected_output=(
            "Report insider e flussi di capitale in italiano con le 4 tabelle indicate (Movimenti, SBC, Istituzionali, Short Interest) "
            "e l'Insider & Ownership Score finale."
        ),
        agent=insider_analyst
    )

    execution_task = Task(
        description=(
            f"[DATA: {today}] Sei il Chief Investment Officer. Leggi TUTTE le analisi settoriali e le tabelle prodotte dagli analisti quantitativi, legali, sentiment e insider su {ticker} "
            "e redigi il DOSSIER DI DUE DILIGENCE ASIMMETRICO finale in Markdown italiano. "
            "Devi seguire RIGOROSAMENTE questa struttura e inserire tutte le tabelle prodotte dagli analisti:\n\n"
            "# 📊 DOSSIER DI DUE DILIGENCE ASIMMETRICO — {ticker} — {today}\n\n"
            "**DATA**: {today}  \n"
            "**TITOLO**: {ticker}  \n"
            "**EMITTENTE**: [Nome completo emittente]  \n"
            "**MARKET CAP**: [Valore stimato o reale]  \n"
            "**PREZZO IMPLICITO**: [Prezzo ad azione corrente]  \n\n"
            "## 1. 📊 VALUTAZIONE & RISCHIO QUANTITATIVO\n"
            "[Inserisci la Tabella Multipli di Valutazione]\n"
            "[Inserisci la Tabella Trend Margini]\n"
            "[Inserisci la Tabella Profilo Debito & Struttura Capitale]\n"
            "[Inserisci la Tabella Earnings Surprise History]\n"
            "[Inserisci la Tabella Prossimo Catalizzatore]\n"
            "**Quantitative Risk Score**: X/100 — [Giudizio Rischio]\n"
            "**Verdetto Quantitativo**: [Testo del verdetto]\n\n"
            "## 2. 📋 NARRATIVA TRIMESTRALE (10-Q)\n"
            "### Dichiarazioni Chiave del Management (MD&A)\n"
            "[Inserisci le citazioni letterali del management con la relative Traduzioni in grassetto]\n"
            "### Nuovi Rischi Divulgati\n"
            "[Inserisci l'elenco dei rischi]\n"
            "**Valutazione Narrativa**: [Orso/Toro/Cauto con spiegazione]\n\n"
            "## 3. ⚖️ RED FLAG LEGALI & PRECEDENTI STORICI\n"
            "### Matrice delle Bandiere Rosse Forensi\n"
            "[Inserisci la Tabella Matrice Bandiere Rosse]\n"
            "### Esposizione Legale Stimata\n"
            "[Inserisci la Tabella Esposizione Legale]\n"
            "### Precedenti Storici\n"
            "[Inserisci l'elenco dei paralleli storici trovati o la dicitura 'VAULT GRAVEMENTE CARENTE' se non ci sono]\n"
            "**Forensic Legal Risk Score**: X/100 — [Giudizio Rischio]\n\n"
            "## 4. 🌐 SENTIMENT SOCIAL & ALTERNATIVE DATA\n"
            "### Mappa del Sentiment\n"
            "[Inserisci la Tabella Mappa del Sentiment]\n"
            "### Rumor Principali in Circolazione\n"
            "[Inserisci la Tabella Rumor]\n"
            "**Sentiment Composito**: [Punteggio e giudizio]\n\n"
            "## 5. 🕵️ ANALISI INSIDER & PROPRIETÀ ISTITUZIONALE\n"
            "### Movimenti Insider\n"
            "[Inserisci la Tabella Movimenti]\n"
            "### Stock Based Compensation — L'Emorragia\n"
            "[Inserisci la Tabella SBC]\n"
            "### Proprietà Istituzionale\n"
            "[Inserisci la Tabella Istituzionali]\n"
            "### Short Interest\n"
            "[Inserisci la Tabella Short Interest]\n"
            "**Insider & Ownership Score**: X/100\n\n"
            "## 6. 🎯 VERDETTO FINALE\n"
            "### Score Composito Finale\n"
            "Tabella con colonne: Asse | Punteggio | Peso | Contributo. Righe per i 5 assi e riga finale del TOTALE COMPOSITO.\n\n"
            "**🎯 POSIZIONE**: LONG / SHORT / PASS (giudizio netto)\n\n"
            "### Parametri Operativi\n"
            "Tabella con colonne: Parametro | Valore. Righe: Direzione, Confidenza, Entry, Target Prezzo (12 mesi), Downside Estremo, Potenziale Ribasso, Stop Loss, Orizzonte, Dimensione, Risk/Reward.\n\n"
            "### La Tesi in 10 Punti\n"
            "[Fornisci una lista numerata di 10 punti precisi e argomentati che riassumono la tesi di investimento asimmetrica]\n\n"
            "### Rischi alla Tesi\n"
            "Tabella con colonne: Rischio | Probabilità | Mitigazione.\n\n"
            "**Caso Base**: [Prezzo target e spiegazione]\n"
            "**Caso Pessimo**: [Prezzo target e spiegazione]\n\n"
            "🔴 **VERDETTO ESECUTIVO FINALE**\n"
            "[Testo di verdetto esecutivo finale, profondo, asimmetrico e incisivo, che spiega perché l'asset è o non è un investimento sostenibile]\n\n"
            "Classificazione: RIGOROSAMENTE CONFIDENZIALE — SOLO PER USO INTERNO"
        ),
        expected_output=(
            "Dossier di due diligence asimmetrico finale in italiano strutturato esattamente secondo il template Markdown specificato, "
            "completo di tutte le tabelle, i punteggi parziali e il verdetto esecutivo finale."
        ),
        agent=executioner,
        context=[quant_task, quarterly_task, audit_task, alt_data_task, insider_task]
    )

    # ==========================================
    # CREW EXECUTION
    # ==========================================

    dd_crew = Crew(
        agents=[quant_analyst, quarterly_analyst, forensic_auditor, alt_data_analyst, insider_analyst, executioner],
        tasks=[quant_task, quarterly_task, audit_task, alt_data_task, insider_task, execution_task],
        process=Process.sequential,
        verbose=True
    )

    result = dd_crew.kickoff()
    final_report = str(result)

    # Salvataggio locale
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("saved_research", exist_ok=True)
    filename = f"saved_research/{ticker}_{timestamp}.md"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(final_report)
        logger.info(f"Report salvato in {filename}")
    except Exception as e:
        logger.error(f"Errore salvataggio report: {e}")

    # Ingestione in ChromaDB per memoria storica
    memory = get_memory()
    if memory is not None:
        try:
            memory.ingest_data(ticker, final_report)
        except Exception as e:
            logger.error(f"Errore ingestione SuperMemory: {e}")

    return final_report


if __name__ == "__main__":
    test_ticker = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    print(f"\n[ORCHESTRATOR] Avvio Dossier per {test_ticker}...\n")
    report = run_due_diligence(test_ticker)
    print("\n================ FINAL DOSSIER ================\n")
    print(report)
    print("\n===============================================\n")
