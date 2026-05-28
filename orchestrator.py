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

# Importazione dei pilastri creati nei task precedenti
from sensors import QuantSensor, LegalSensor, QuarterlySensor, AlternativeDataSensor, InsiderSensor
from supermemory import SuperMemory

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Caricamento Variabili d'Ambiente (.env)
load_dotenv()

# Inizializzazione DeepSeek V4 Pro tramite l'interfaccia LLM di CrewAI (basata su LiteLLM)
deepseek_llm = LLM(
    model="deepseek/deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# Inizializzazione Supermemoria Condivisa
try:
    memory = SuperMemory()
except Exception as e:
    logger.error(f"Orchestrator: Errore inizializzazione SuperMemory: {e}")
    memory = None

# ==========================================
# DEFINIZIONE TOOLS PER GLI AGENTI CREWAI
# ==========================================

@tool("Get Quantitative Data")
def get_quant_data(ticker: str) -> str:
    """
    Extracts full fundamental data: P/E, EV/EBITDA, P/S, P/B, EBITDA, Gross/Operating/Net Margins,
    ROE, ROA, Debt/Equity, Current Ratio, Free Cash Flow, Operating Cash Flow, Revenue Growth,
    Earnings Growth, 3-year Income Statement, Cash Flow Statement, Balance Sheet,
    Earnings Surprise History (EPS Actual vs Estimated), and upcoming Earnings Calendar.
    """
    return QuantSensor.extract(ticker)

@tool("Get Legal Data")
def get_legal_data(ticker: str) -> str:
    """
    Extracts Risk Factors and Legal Proceedings from the latest 
    SEC 10-K annual filing for a given stock ticker.
    """
    return LegalSensor.extract(ticker)

@tool("Get Quarterly Report Data")
def get_quarterly_data(ticker: str) -> str:
    """
    Downloads the latest SEC 10-Q quarterly filing and extracts:
    - Item 2 (MD&A): Management's Discussion & Analysis — the core quarterly narrative 
      with revenue commentary, segment performance, and forward guidance.
    - Item 1A: Updated Risk Factors for the quarter.
    Use this to understand what the company's own management said about the most recent quarter.
    """
    return QuarterlySensor.extract(ticker)

@tool("Get Alternative Data")
def get_alt_data(ticker: str) -> str:
    """
    Uses an MCP Server (Brave Search) to scrape Twitter/X and Reddit (WallStreetBets) 
    for real-time retail sentiment, breaking news, and social media hype regarding the ticker.
    """
    return AlternativeDataSensor.extract(ticker)

@tool("Get Insider and Ownership Data")
def get_insider_data(ticker: str) -> str:
    """
    Extracts insider transactions (CEO/CFO buys and sells), institutional holders 
    (which major funds own the stock), and short interest data.
    """
    return InsiderSensor.extract(ticker)


@tool("Search Historical Context")
def search_historical_context(query: str) -> str:
    """
    Searches the local ChromaDB vector database for historically 
    similar cases or anomalies based on a semantic query.
    """
    if memory is None:
        return json.dumps({"error": "Vector database unavailable."})
    
    # Richiede top 3 risultati
    results = memory.query_context(query, n_results=3)
    return json.dumps(results, indent=2, ensure_ascii=False)

# ==========================================
# CREAZIONE DEL TRIUMVIRATO DI AGENTI
# ==========================================

def run_due_diligence(ticker: str, step_callback=None) -> str:
    today = datetime.datetime.now().strftime("%A %d %B %Y")
    logger.info(f"Avvio Penta-Agenti CrewAI per la Due Diligence su: {ticker.upper()} — Data: {today}")
    
    # 1. QUANT ANALYST
    quant_analyst = Agent(
        role='Senior Quantitative Analyst',
        goal=f'TODAY IS {today}. You MUST use ONLY data from today or the most recent available period. Analyze ALL financial multiples deeply: P/E, EV/EBITDA, P/S, P/B, EBITDA, gross/operating/net margins, ROE, ROA, FCF, debt levels, and growth rates. Evaluate 3-year income statement, cashflow, and balance sheet trends. Flag earnings surprises (beat/miss vs estimates). DEVI SCRIVERE TUTTI I TUOI RAGIONAMENTI IN LINGUA ITALIANA.',
        backstory='You are a ruthless, numbers-driven quant from a top tier activist hedge fund. You examine every line of the income statement, cashflow and balance sheet. If margins are contracting, debt is rising, or FCF is negative while the stock trades at a premium, you recommend a short. You rely exclusively on the data provided by your tools.',
        tools=[get_quant_data],
        llm=deepseek_llm,
        verbose=True,
        step_callback=step_callback
    )

    # 2. QUARTERLY ANALYST
    quarterly_analyst = Agent(
        role='Quarterly Intelligence Analyst',
        goal='Extract and interpret the most recent 10-Q quarterly report from the SEC. Summarize what management SAID about the quarter (MD&A), identify forward guidance, segment performance, and any new risks disclosed for the quarter. DEVI SCRIVERE IL TUO REPORT IN LINGUA ITALIANA.',
        backstory='You are a specialist in reading between the lines of quarterly filings. You know that companies bury bad news in footnotes and use vague language to hide deterioration. You extract the MD&A and flag any soft language that hides weakness.',
        tools=[get_quarterly_data],
        llm=deepseek_llm,
        verbose=True,
        step_callback=step_callback
    )

    # 3. FORENSIC AUDITOR
    forensic_auditor = Agent(
        role='Forensic Legal Auditor',
        goal='Scrutinize SEC 10-K filings for hidden legal risks, pending lawsuits, and cross-reference them with historical database precedents. DEVI SCRIVERE TUTTI I TUOI RAGIONAMENTI IN LINGUA ITALIANA.',
        backstory='You are a paranoid ex-SEC regulator. You read between the lines of risk factors to find what the company is trying to hide. You ALWAYS use the historical context tool to see if similar risks led to disasters in the past for other companies.',
        tools=[get_legal_data, search_historical_context],
        llm=deepseek_llm,
        verbose=True,
        step_callback=step_callback
    )

    # 4. ALTERNATIVE DATA ANALYST
    alt_data_analyst = Agent(
        role='Alternative Data & Sentiment Analyst',
        goal='Analyze real-time social media sentiment from Twitter/X and Reddit (WallStreetBets) using the MCP Server. Determine if the retail and institutional sentiment is bullish or bearish. DEVI SCRIVERE IL TUO REPORT IN LINGUA ITALIANA.',
        backstory='You are a modern data miner. You don\'t care about balance sheets; you care about hype, momentum, and crowd psychology. You know that a stock can rally on terrible earnings if the Twitter sentiment is euphoric.',
        tools=[get_alt_data],
        llm=deepseek_llm,
        verbose=True,
        step_callback=step_callback
    )

    # 5. INSIDER & OWNERSHIP ANALYST
    insider_analyst = Agent(
        role='Insider Trading & Ownership Analyst',
        goal='Analyze insider transactions (buys/sells by executives) and institutional ownership. Determine if the "smart money" is entering or exiting the position. Evaluate short interest levels. DEVI SCRIVERE IL TUO REPORT IN LINGUA ITALIANA.',
        backstory='You are a detective of capital flows. You know that insiders sell for many reasons, but they only buy for one: they think the price will go up. You flag massive sales by CEOs or CFOs as critical red flags.',
        tools=[get_insider_data],
        llm=deepseek_llm,
        verbose=True,
        step_callback=step_callback
    )

    # 6. THE EXECUTIONER
    executioner = Agent(
        role='Chief Investment Officer (The Executioner)',
        goal='Synthesize ALL five analyses (Quantitative, Quarterly Narrative, Legal, Social Sentiment, Insider/Ownership) into a definitive asymmetrical Markdown report. IL REPORT FINALE DEVE ESSERE SCRITTO RIGOROSAMENTE IN UN ITALIANO PROFESSIONALE ED ELEGANTE.',
        backstory='You are the ultimate decision maker. You integrate quant numbers, quarterly narratives, legal risks, social momentum, and insider flows to produce a final verdict. You write concise, military-grade financial reports.',
        llm=deepseek_llm,
        verbose=True,
        step_callback=step_callback
    )


    # ==========================================
    # DEFINIZIONE DEI TASK
    # ==========================================

    quant_task = Task(
        description=f'[DATA ODIERNA: {today}] Extract and deeply analyze ALL financial data for {ticker} as of today. Include EBITDA, EV/EBITDA, P/S, P/B, gross/operating/net margins, ROE, ROA, FCF, debt/equity, current ratio. Review 3-year income statement, cashflow, and balance sheet for structural trends. Identify any earnings beats or misses vs analyst estimates. Report the next earnings date from the calendar.',
        expected_output='A detailed quantitative breakdown: valuation multiples table, margin trend analysis (3Y), debt profile assessment, FCF analysis, earnings surprise history, next catalyst date. Include a Quantitative Risk Score (0-100).',
        agent=quant_analyst
    )

    quarterly_task = Task(
        description=f'[DATA ODIERNA: {today}] Download and read the most recent SEC 10-Q quarterly filing for {ticker}. Extract what management actually SAID about the quarter in the MD&A section. Identify: revenue commentary, segment performance, cost trends, and any forward guidance or warnings.',
        expected_output='A quarterly intelligence summary: key management statements from MD&A, any new risks disclosed, segment performance highlights, and a Narrative Risk Assessment (Bullish/Neutral/Bearish).',
        agent=quarterly_analyst
    )

    audit_task = Task(
        description=f'[DATA ODIERNA: {today}] Extract the 10-K legal data for {ticker}. Analyze the Risk Factors and Legal Proceedings. Query the historical database for precedents.',
        expected_output='A forensic legal report highlighting major red flags, potential lawsuits, and comparison with historical precedents from the vault.',
        agent=forensic_auditor
    )

    alt_data_task = Task(
        description=f'[DATA ODIERNA: {today}] Scrape Twitter/X and Reddit for {ticker} using the Alternative Data MCP tool. Analyze the current hype, opinions, and overall sentiment as of today.',
        expected_output='A sentiment report stating whether the crowd is Bullish or Bearish, highlighting any major rumors or momentum shifts.',
        agent=alt_data_analyst
    )

    insider_task = Task(
        description=f'[DATA ODIERNA: {today}] Analyze the insider transactions and institutional ownership for {ticker}. Check if executives are buying or selling recently. Review the short interest percentage of float.',
        expected_output='An ownership report highlighting major insider moves, institutional stability, and short squeeze potential.',
        agent=insider_analyst
    )

    execution_task = Task(
        description=f'[DATA ODIERNA: {today}] Read ALL five analyses (Quant, Quarterly, Legal, Social Sentiment, Insider Flows) for {ticker}. Produce a final Markdown report with these exact sections:\n1. 📊 Valutazione & Rischio Quantitativo\n2. 📋 Narrativa Trimestrale (10-Q)\n3. ⚖️ Red Flag Legali & Precedenti Storici\n4. 🌐 Sentiment Social & Alternative Data\n5. 🕵️ Analisi Insider & Proprietà Istituzionale\n6. 🎯 Verdetto Finale (LONG / SHORT / PASS) con rationale e livello di confidenza 0-100.\nNota: Includi sempre la data {today} nell\'intestazione del report.',
        expected_output='Un dossier di due diligence completo, strutturato e asimmetrico in Italiano professionale.',
        agent=executioner,
        context=[quant_task, quarterly_task, audit_task, alt_data_task, insider_task]
    )


    # ==========================================
    # ESECUZIONE DELLA CREW (Processo Sequenziale)
    # ==========================================
    
    dd_crew = Crew(
        agents=[quant_analyst, quarterly_analyst, forensic_auditor, alt_data_analyst, insider_analyst, executioner],
        tasks=[quant_task, quarterly_task, audit_task, alt_data_task, insider_task, execution_task],
        process=Process.sequential,
        verbose=True
    )

    # Kickoff restituisce un oggetto CrewOutput (su CrewAI moderno)
    result = dd_crew.kickoff()
    
    final_report = str(result)
    
    # Post-Elaborazione: Salvataggio locale in Markdown per il sistema Cartelle
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("saved_research", exist_ok=True)
    filename = f"saved_research/{ticker}_{timestamp}.md"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(final_report)
        logger.info(f"Report esportato con successo in {filename}")
    except Exception as e:
        logger.error(f"Errore durante il salvataggio del file locale: {e}")

    # Post-Elaborazione: Ingestione del Dossier nella Supermemoria per arricchire la conoscenza storica
    if memory is not None:
        try:
            logger.info("Salvataggio del report finale nella Supermemoria...")
            memory.ingest_data(ticker, final_report)
        except Exception as e:
            logger.error(f"Errore durante l'ingestione del report: {e}")
            
    return final_report

if __name__ == "__main__":
    import sys
    # Esecuzione via CLI per testing (es: python orchestrator.py MSFT)
    test_ticker = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    print(f"\n[ORCHESTRATOR] Inizio generazione Dossier per {test_ticker}...\n")
    
    report = run_due_diligence(test_ticker)
    
    print("\n================ FINAL DOSSIER ================\n")
    print(report)
    print("\n===============================================\n")
