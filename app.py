import streamlit as st
import json
import os
import logging
import base64
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from streamlit_echarts import st_echarts
from streamlit_extras.metric_cards import style_metric_cards
from openai import OpenAI
from dotenv import load_dotenv
import sys
import io
import time
import datetime
import pandas as pd
from orchestrator import run_due_diligence


@st.cache_data(ttl=30, show_spinner=False)
def search_ticker_yahoo(query: str) -> list[dict]:
    """Ricerca ticker in tempo reale su Yahoo Finance tramite yf.Search."""
    if not query or len(query) < 2:
        return []
    try:
        results = yf.Search(query, max_results=8)
        quotes = results.quotes
        output = []
        for q in quotes:
            symbol = q.get("symbol", "")
            name = q.get("shortname") or q.get("longname") or symbol
            exchange = q.get("exchange", "")
            q_type = q.get("quoteType", "")
            if symbol:
                output.append({
                    "label": f"{symbol} — {name} ({exchange})",
                    "ticker": symbol,
                    "name": name,
                    "type": q_type
                })
        return output
    except Exception as e:
        logger.warning(f"Errore ricerca ticker '{query}': {e}")
        return []

# Caricamento Variabili d'Ambiente (.env)
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# UI CONFIGURATION & HIGH-END CSS
# ==========================================
st.set_page_config(
    page_title="Automated Due Diligence Terminal", 
    page_icon="", 
    layout="wide"
)
CSS_INJECTION = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');

/* Typography & Base Setup */
html, body, [class*="css"] {
    font-family: 'Space Grotesk', sans-serif !important;
}

[data-testid="stAppViewContainer"] {
    background-color: #050505 !important;
    background-image: radial-gradient(circle at 50% 0%, rgba(30,50,40,0.15), rgba(5,5,5,1) 60%) !important;
    color: #EAEAEA !important;
}

[data-testid="stHeader"] { background: transparent; }

/* Tabs Styling */
[data-baseweb="tab-list"] {
    gap: 12px;
    background: transparent;
    padding-bottom: 10px;
    border-bottom: none !important;
}
[data-baseweb="tab"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 50px !important;
    padding: 8px 24px !important;
    color: #A0A0A0 !important;
    backdrop-filter: blur(10px);
}
[data-baseweb="tab"][aria-selected="true"] {
    background: rgba(255,255,255,0.12) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
[data-baseweb="tab-highlight"] { display: none !important; }

/* Containers (Metrics, Chat, Inputs) - CONTRAST FIX */
div[data-testid="stMetric"], 
div[data-testid="stChatMessage"], 
div[data-testid="stMarkdownContainer"] pre,
.stTextArea textarea, 
.stTextInput input, 
[data-baseweb="select"] > div {
    background-color: #121212 !important; /* Sfondo solido scuro per forzare il contrasto */
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 12px !important;
    padding: 16px !important;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.5) !important;
    color: #FFFFFF !important;
}

/* Input Fields & Autofill - CONTRAST FIX */
.stTextInput input, 
.stTextArea textarea, 
[data-baseweb="select"] input { 
    color: #FFFFFF !important; 
    -webkit-text-fill-color: #FFFFFF !important; 
}
.stTextInput input::placeholder { color: #888888 !important; }

/* Dropdown Menu Popover - CONTRAST FIX */
div[data-baseweb="popover"] > div, ul[role="listbox"], li[role="option"] {
    background-color: #1A1A1A !important;
    color: #FFFFFF !important;
}
li[role="option"]:hover, li[role="option"][aria-selected="true"] {
    background-color: #333333 !important;
    color: #00FF88 !important;
}

/* Markdown & test content explicit bright colors */
.stMarkdown p, .stMarkdown li, .stChatMessage p, .stChatMessage li, [data-testid="stMarkdownContainer"] {
    color: #EAEAEA !important;
}
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4, .stMarkdown h5, .stMarkdown h6,
.stChatMessage h1, .stChatMessage h2, .stChatMessage h3, .stChatMessage h4, .stChatMessage h5, .stChatMessage h6 {
    color: #FFFFFF !important;
}

/* Metric Colors */
[data-testid="stMetricLabel"] {
    color: #AAAAAA !important;
}
[data-testid="stMetricValue"] {
    color: #FFFFFF !important;
}

/* Button Styling (Professional & Clean) */
.stButton > button {
    background-color: #FFFFFF !important;
    color: #000000 !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 10px 24px !important;
    font-weight: 600 !important;
    transition: background-color 0.2s ease !important;
}
.stButton > button p {
    color: #000000 !important;
    font-weight: 600 !important;
}
.stButton > button:hover {
    background-color: #E0E0E0 !important;
}

/* Hide Default Chrome */
footer {visibility: hidden !important;}
#MainMenu {visibility: hidden !important;}

.block-container {
    padding-top: 4rem;
    padding-bottom: 4rem;
    max-width: 1400px !important;
}
</style>
"""
st.markdown(CSS_INJECTION, unsafe_allow_html=True)

st.title("ASYMMETRIC INTELLIGENCE TERMINAL")

# Definizione dei 5 Tab (Aggiunto "Cartelle")
tab_strategy_hub, tab_direct_intel, tab_portfolio, tab_vault, tab_folders = st.tabs([
    "Strategy Hub",
    "Direct Intel", 
    "Portfolio Live", 
    "Vault",
    "Cartelle"
])

# Inizializzazione chiavi nella barra laterale
st.sidebar.title("🔑 API Configuration")
st.sidebar.markdown("Se non inserisci una chiave personale qui, verrà utilizzata quella di default configurata sul server (se presente).")

deepseek_api_key = st.sidebar.text_input(
    "DeepSeek API Key",
    type="password",
    value=os.getenv("DEEPSEEK_API_KEY", ""),
    help="Inserisci la tua chiave API personale di DeepSeek. Non verrà memorizzata."
)

client = None
if deepseek_api_key:
    client = OpenAI(api_key=deepseek_api_key, base_url="https://api.deepseek.com/v1")

# ==========================================
# TAB 1: STRATEGY HUB
# ==========================================
with tab_strategy_hub:
    st.header("STRATEGY HUB")
    today_str = datetime.datetime.now().strftime("%d %B %Y")  # es: 28 Aprile 2026
    st.markdown(f"Genera un dossier asimmetrico in lingua italiana. Analisi basata su dati aggiornati al: **{today_str}**.")
    st.markdown("---")

    # --- RICERCA TICKER TIPO GOOGLE O INSERIMENTO DIRETTO ---
    st.markdown("##### Cerca per Nome o Inserisci il Codice")
    
    col_search, col_direct = st.columns(2)
    with col_search:
        search_query = st.text_input(
            "Cerca per Nome dell'Azienda:",
            key="ticker_search",
            placeholder="Es: Apple, Tesla, S&P 500..."
        )
    with col_direct:
        direct_ticker = st.text_input(
            "Oppure inserisci il Codice (Ticker, ISIN o Numerico/CIK):",
            key="ticker_direct",
            placeholder="Es: AAPL, US0378331005, 0000320193"
        ).upper()

    ticker_input = ""
    company_name_display = ""

    # Logica di priorità: L'inserimento diretto sovrascrive la ricerca
    if direct_ticker:
        ticker_input = direct_ticker
        # Fetch veloce del nome se inserito manualmente
        try:
            with st.spinner("Identificazione azienda..."):
                t_info = yf.Ticker(ticker_input).info
                company_name_display = t_info.get("longName") or t_info.get("shortName") or ticker_input
            st.success(f"Analisi pronta per: **{company_name_display}** ({ticker_input})")
        except:
            company_name_display = ticker_input
            st.info(f"Ticker rilevato: **{ticker_input}**")
    elif search_query:
        with st.spinner("Ricerca in corso su Yahoo Finance..."):
            results = search_ticker_yahoo(search_query)

        if results:
            options = [r["label"] for r in results]
            selected_label = st.selectbox(
                "Seleziona il titolo corretto dai risultati:",
                options,
                key="ticker_select"
            )
            selected_info = next((r for r in results if r["label"] == selected_label), None)
            if selected_info:
                ticker_input = selected_info["ticker"]
                company_name_display = selected_info.get("name", ticker_input)
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Ticker Selezionato", ticker_input)
                col_b.metric("Azienda", company_name_display)
                col_c.metric("Tipo", selected_info.get("type", "N/A"))
        else:
            st.warning("Nessun risultato trovato. Prova a inserire direttamente il codice Ticker nel box di destra.")

    st.markdown("")
    if st.button(f"🚀 Avvia Due Diligence — {today_str}", disabled=(not ticker_input)):
        today_full = datetime.datetime.now().strftime("%A %d %B %Y, ore %H:%M")
        
        # ---------- SETUP PROGRESS ----------
        status_box = st.status(f"📡 Connessione ai sensori per {company_name_display}...", expanded=True)
        progress_bar = st.progress(0, text="Inizializzazione...")
        time_display = st.empty()
        
        # Lista dei 6 step con descrizione e fonte
        AGENT_STEPS = [
            {"name": "Analista Quantitativo",    "icon": "📊", "fonte": "Yahoo Finance (yfinance)",             "step": 1},
            {"name": "Analista Trimestrali",     "icon": "📋", "fonte": "SEC EDGAR — Form 10-Q",               "step": 2},
            {"name": "Auditor Forense",          "icon": "⚖️", "fonte": "SEC EDGAR — Form 10-K",               "step": 3},
            {"name": "Analista Sentiment Social", "icon": "🌐", "fonte": "MCP Brave Search (Twitter/Reddit)",   "step": 4},
            {"name": "Analista Insider",         "icon": "🕵️", "fonte": "Yahoo Finance — Insider Transactions", "step": 5},
            {"name": "Executioner (CIO)",        "icon": "🎯", "fonte": "Sintesi dei 5 report precedenti",      "step": 6},
        ]
        TOTAL_STEPS = len(AGENT_STEPS)
        AVG_SECONDS_PER_STEP = 25  # stima conservativa per agente
        
        # Tracciamento runtime degli agenti
        agent_log = []  # Lista di dict per la tasca a scomparsa
        
        # Buffer stdout
        output_buffer = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = output_buffer
        
        # Step counter nel session state per evitare re-runs
        st.session_state["_step_idx"] = 0
        start_time = time.time()
        
        def crew_step_callback(step):
            idx = st.session_state.get("_step_idx", 0)
            idx = min(idx, TOTAL_STEPS - 1)
            current_agent = AGENT_STEPS[idx]
            
            # Aggiorna progresso
            percent = int(((idx + 1) / TOTAL_STEPS) * 100)
            progress_bar.progress(
                percent,
                text=f"{current_agent['icon']} [{idx+1}/{TOTAL_STEPS}] {current_agent['name']} in esecuzione..."
            )
            
            # Stima tempo rimanente
            elapsed = time.time() - start_time
            remaining = max(0, (TOTAL_STEPS - idx - 1) * AVG_SECONDS_PER_STEP)
            time_display.markdown(
                f"⏱️ Trascorso: **{int(elapsed)}s** — Tempo stimato rimanente: **~{remaining}s**"
            )
            
            # Log per la tasca a scomparsa
            try:
                tool_used = getattr(step, 'tool', current_agent['fonte'])
            except:
                tool_used = current_agent['fonte']
            
            agent_log.append({
                "step": idx + 1,
                "agente": current_agent['name'],
                "icon": current_agent['icon'],
                "fonte": current_agent['fonte'],
                "tool": tool_used,
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
            })
            
            # Messaggio live nello status
            status_box.write(f"{current_agent['icon']} **[{idx+1}/{TOTAL_STEPS}] {current_agent['name']}** — Fonte: `{current_agent['fonte']}`")
            
            st.session_state["_step_idx"] = idx + 1

        try:
            status_box.write(f"🗓️ Data analisi: **{today_full}** — Dati aggiornati a oggi.")
            status_box.write("🚀 Avvio pipeline 6-agenti...")
            
            report = run_due_diligence(ticker_input, step_callback=crew_step_callback, api_key=deepseek_api_key)
            
            sys.stdout = old_stdout
            logs = output_buffer.getvalue()
            elapsed_total = int(time.time() - start_time)
            
            progress_bar.progress(100, text=f"✅ Completato in {elapsed_total}s")
            time_display.markdown(f"✅ **Analisi completata in {elapsed_total} secondi.**")
            status_box.update(label=f"Dossier completato: {company_name_display} ({today_str})", state="complete", expanded=False)
            
            st.success(f"Dossier salvato in 📂 Cartelle.")
            st.markdown("---")
            
            # ==========================================
            # LAYOUT: REPORT + GRAFICI AFFIANCATI
            # ==========================================
            col_report, col_charts = st.columns([6, 4])
            
            with col_report:
                st.markdown(report)
                
                # -------- TASCA A SCOMPARSA --------
                with st.expander("🔍 Intelligence Audit — Chi ha fatto cosa & Fonti"):
                    st.markdown(f"**Data Analisi:** {today_full}")
                    st.markdown(f"**Ticker:** `{ticker_input}` — {company_name_display}")
                    st.markdown("---")
                    for entry in agent_log:
                        st.markdown(
                            f"{entry['icon']} **Step {entry['step']}/6 — {entry['agente']}**  \n"
                            f"🕐 Eseguito alle: `{entry['timestamp']}`  \n"
                            f"📡 Fonte dati: `{entry['fonte']}`"
                        )
                        st.markdown("")
                    st.markdown("---")
                    st.markdown("**Log Tecnico Completo degli Agenti:**")
                    st.code(logs, language="text")
            
            with col_charts:
                # -------------------------
                # RADAR CHART (Echarts)
                # -------------------------
                st.markdown("##### 📡 Telemetria Rischio (Quant proxy)")
                try:
                    info = yf.Ticker(ticker_input).info
                    
                    # 1. Valutazione (P/E proxy)
                    pe = info.get('trailingPE', 25)
                    val_score = max(0, min(100, 100 - (pe - 10) * 2)) if pe else 50
                    
                    # 2. Profittabilità (Gross margin proxy)
                    margin = info.get('grossMargins', 0.3)
                    prof_score = max(0, min(100, margin * 200)) if margin else 50
                    
                    # 3. Crescita (Revenue Growth proxy)
                    rev_growth = info.get('revenueGrowth', 0.1)
                    growth_score = max(0, min(100, 50 + rev_growth * 200)) if rev_growth else 50
                    
                    # 4. Liquidità (Current Ratio proxy)
                    c_ratio = info.get('currentRatio', 1.5)
                    liq_score = max(0, min(100, c_ratio * 30)) if c_ratio else 50
                    
                    # 5. Sentiment (Proxy based on PE & general health)
                    sent_score = max(0, min(100, 100 - (pe - 15) * 1.5)) if pe else 50
                    
                    radar_options = {
                        "backgroundColor": "transparent",
                        "radar": {
                            "indicator": [
                                {"name": "Valutazione", "max": 100},
                                {"name": "Profittabilità", "max": 100},
                                {"name": "Crescita", "max": 100},
                                {"name": "Liquidità", "max": 100},
                                {"name": "Sentiment", "max": 100}
                            ],
                            "splitArea": {"show": False},
                            "axisLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}},
                            "splitLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}},
                            "name": {"textStyle": {"color": "#EAEAEA", "fontFamily": "Space Mono"}}
                        },
                        "series": [{
                            "name": "Rischio",
                            "type": "radar",
                            "data": [
                                {
                                    "value": [val_score, prof_score, growth_score, liq_score, sent_score],
                                    "name": ticker_input,
                                    "areaStyle": {"color": "rgba(74, 246, 38, 0.2)"},
                                    "lineStyle": {"color": "#4AF626"},
                                    "itemStyle": {"color": "#4AF626"}
                                }
                            ]
                        }]
                    }
                    st_echarts(radar_options, height="350px")
                except Exception as e:
                    st.warning(f"Dati Radar limitati: {e}")
                
                st.markdown("---")
                
                # -------------------------
                # CANDLESTICK CHART (Plotly)
                # -------------------------
                st.markdown("##### 📈 Price Action Storica (6 Mesi)")
                try:
                    hist = yf.Ticker(ticker_input).history(period="6mo")
                    if not hist.empty:
                        fig = go.Figure(data=[go.Candlestick(
                            x=hist.index,
                            open=hist['Open'],
                            high=hist['High'],
                            low=hist['Low'],
                            close=hist['Close'],
                            increasing_line_color='#4AF626', 
                            decreasing_line_color='#FF2A2A'
                        )])
                        fig.update_layout(
                            template="plotly_dark",
                            margin=dict(l=0, r=0, t=0, b=0),
                            height=350,
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            xaxis_rangeslider_visible=False,
                            font=dict(family="Space Mono", color="#EAEAEA")
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Dati storici non disponibili.")
                except Exception as e:
                    st.warning(f"Errore grafico: {e}")
            
        except Exception as e:
            sys.stdout = old_stdout
            status_box.update(label="Errore durante l'analisi", state="error")
            st.error(f"Errore critico: {e}")

# ==========================================
# TAB 2: DIRECT INTEL
# ==========================================
with tab_direct_intel:
    st.header("DIRECT INTEL")
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Richiedi intel macro-economico o news sentiment..."):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if client:
                try:
                    response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.chat_messages]
                    )
                    reply = response.choices[0].message.content
                    st.markdown(reply)
                    st.session_state.chat_messages.append({"role": "assistant", "content": reply})
                except Exception as e:
                    st.error(f"Errore API: {e}")
            else:
                st.error("Client API non configurato.")

# ==========================================
# TAB 3: PORTFOLIO (VISION & PLOTLY)
# ==========================================
with tab_portfolio:
    st.header("PORTFOLIO LIVE")
    st.markdown("Costruisci o modifica il tuo portafoglio per un'analisi asimmetrica dell'esposizione e del rischio.")
    st.markdown("---")

    # Inizializzazione dati di esempio o caricamento da file
    import os
    import json
    
    portfolio_file = "portfolio.json"
    default_data = []
    if os.path.exists(portfolio_file):
        try:
            with open(portfolio_file, "r") as f:
                loaded_data = json.load(f)
                if loaded_data and isinstance(loaded_data, list):
                    # Adattiamo i vecchi formati se necessario
                    for item in loaded_data:
                        if "ticker" in item and "Ticker" not in item:
                            item["Ticker"] = item.pop("ticker")
                        if "percentage" in item and "Quantità" not in item:
                            item["Quantità"] = item.pop("percentage")
                        if "Prezzo_Acquisto" not in item:
                            item["Prezzo_Acquisto"] = 0.0
                    default_data = loaded_data
        except Exception as e:
            st.error(f"Errore caricamento portafoglio: {e}")

    if not default_data:
        default_data = [
            {"Ticker": "AAPL", "Quantità": 10, "Prezzo_Acquisto": 150.0},
            {"Ticker": "MSFT", "Quantità": 5, "Prezzo_Acquisto": 280.0},
            {"Ticker": "SPY", "Quantità": 2, "Prezzo_Acquisto": 400.0}
        ]
    
    # Editor interattivo
    st.markdown("##### 📝 Asset Manager")
    edited_df = st.data_editor(
        pd.DataFrame(default_data),
        num_rows="dynamic",
        use_container_width=True,
        key="portfolio_editor"
    )

    if st.button("🚀 Aggiorna e Analizza Portafoglio"):
        if edited_df.empty or edited_df["Ticker"].dropna().empty:
            st.warning("Inserisci almeno un asset per procedere.")
        else:
            # Salvataggio persistente del portafoglio
            try:
                valid_df = edited_df.dropna(subset=["Ticker"])
                with open(portfolio_file, "w") as f:
                    json.dump(valid_df.to_dict(orient="records"), f, indent=2)
            except Exception as e:
                st.warning(f"Impossibile salvare il portafoglio: {e}")
                
            with st.spinner("Recupero prezzi live e calcolo metriche..."):
                results = []
                total_invested = 0
                total_current_value = 0
                
                for _, row in edited_df.iterrows():
                    ticker = str(row["Ticker"]).upper().strip()
                    qty = float(row["Quantità"])
                    buy_price = float(row["Prezzo_Acquisto"])
                    
                    if not ticker: continue
                    
                    try:
                        # Recupero prezzo live
                        t = yf.Ticker(ticker)
                        current_price = t.history(period="1d")["Close"].iloc[-1]
                        
                        invested = qty * buy_price
                        current_val = qty * current_price
                        pnl_abs = current_val - invested
                        pnl_pct = (pnl_abs / invested * 100) if invested != 0 else 0
                        
                        # Recupero dati geografici (gestione ETF)
                        country = t.info.get("country")
                        if not country:
                            # Se è un ETF senza paese, inferiamo dalla valuta
                            currency = t.info.get("currency", "")
                            if currency == "USD":
                                country = "United States"
                            elif currency == "EUR":
                                country = "Germany" # Placeholder per Europa per la mappa
                            else:
                                country = "United States" # Default fallback
                                                
                        results.append({
                            "Ticker": ticker,
                            "Settore": t.info.get("sector", "N/A"),
                            "Paese": country,
                            "Quantità": qty,
                            "Prezzo_Acq": buy_price,
                            "Prezzo_Live": current_price,
                            "Valore_Attuale": current_val,
                            "PnL_Abs": pnl_abs,
                            "PnL_Pct": pnl_pct
                        })
                        
                        total_invested += invested
                        total_current_value += current_val
                    except Exception as e:
                        st.error(f"Errore su {ticker}: {e}")

                if results:
                    res_df = pd.DataFrame(results)
                    total_pnl_abs = total_current_value - total_invested
                    total_pnl_pct = (total_pnl_abs / total_invested * 100) if total_invested != 0 else 0
                    
                    # ==========================================
                    # METRIC CARDS
                    # ==========================================
                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric("VALORE TOTALE", f"${total_current_value:,.2f}")
                    col_m2.metric("P&L ASSOLUTO", f"${total_pnl_abs:,.2f}", delta=f"{total_pnl_abs:,.2f}")
                    col_m3.metric("P&L PERCENTUALE", f"{total_pnl_pct:.2f}%", delta=f"{total_pnl_pct:.2f}%")
                    
                    style_metric_cards(
                        background_color="transparent", 
                        border_color="#333333", 
                        border_left_color="#4AF626",
                        border_radius_px=0,
                        box_shadow=False
                    )
                    
                    st.markdown("---")
                    
                    # ==========================================
                    # GRAFICI
                    # ==========================================
                    col_chart1, col_chart2 = st.columns([6, 4])
                    
                    with col_chart1:
                        st.markdown("##### 📈 Dettaglio Asset")
                        st.dataframe(res_df.style.format({
                            "Prezzo_Live": "{:.2f}",
                            "Valore_Attuale": "{:.2f}",
                            "PnL_Abs": "{:.2f}",
                            "PnL_Pct": "{:.2f}%"
                        }), use_container_width=True)
                        
                    with col_chart2:
                        st.markdown("##### 🍩 Allocazione")
                        fig_pie = px.pie(
                            res_df, 
                            values='Valore_Attuale', 
                            names='Ticker', 
                            hole=0.5,
                            template="plotly_dark",
                            color_discrete_sequence=px.colors.sequential.Greens_r
                        )
                        fig_pie.update_layout(
                            margin=dict(l=0, r=0, t=0, b=0),
                            paper_bgcolor="rgba(0,0,0,0)",
                            showlegend=False
                        )
                        st.plotly_chart(fig_pie, use_container_width=True)

                    # ==========================================
                    # MAPPA GEOGRAFICA
                    # ==========================================
                    st.markdown("##### 🌍 Esposizione Geopolitica")
                    geo_df = res_df.groupby("Paese")["Valore_Attuale"].sum().reset_index()
                    
                    fig_map = px.choropleth(
                        geo_df,
                        locations="Paese",
                        locationmode="country names",
                        color="Valore_Attuale",
                        hover_name="Paese",
                        template="plotly_dark",
                        color_continuous_scale="Greens"
                    )
                    fig_map.update_layout(
                        margin=dict(l=0, r=0, t=0, b=0),
                        paper_bgcolor="rgba(0,0,0,0)",
                        geo=dict(bgcolor="rgba(0,0,0,0)", showframe=False, showcoastlines=True)
                    )
                    st.plotly_chart(fig_map, use_container_width=True)

                    # ==========================================
                    # ANALISI STRATEGICA DEEPSEEK
                    # ==========================================
                    st.markdown("---")
                    st.markdown("##### 🎯 Commento Strategico (DeepSeek Intelligence)")
                    
                    if client:
                        with st.spinner("L'intelligenza sta analizzando la tua esposizione..."):
                            portfolio_summary = res_df[["Ticker", "Settore", "Valore_Attuale", "PnL_Pct"]].to_json(orient="records")
                            
                            prompt_strat = f"""
                            Sei un gestore di Hedge Fund istituzionale. Analizza questo portafoglio:
                            {portfolio_summary}
                            
                            Valore Totale: ${total_current_value:,.2f}
                            PnL Totale: {total_pnl_pct:.2f}%
                            
                            Fornisci un'analisi asimmetrica in Italiano:
                            1. Giudizio sull'allocazione (diversificazione, concentrazione).
                            2. Identificazione del rischio principale.
                            3. Suggerimento tattico per ottimizzare il profilo rischio/rendimento.
                            Sii diretto, professionale e sintetico.
                            """
                            
                            try:
                                response = client.chat.completions.create(
                                    model="deepseek-chat",
                                    messages=[{"role": "user", "content": prompt_strat}]
                                )
                                st.info(response.choices[0].message.content)
                            except Exception as e:
                                st.error(f"Errore Analisi LLM: {e}")

# ==========================================
# TAB 4: VAULT
# ==========================================
with tab_vault:
    st.header("VAULT")
    notes_path = "notes.txt"
    try:
        with open(notes_path, "r", encoding="utf-8") as f:
            current_notes = f.read()
    except Exception:
        current_notes = ""
        
    new_notes = st.text_area("Appunti Personali:", value=current_notes, height=300)
    if st.button("Salva nel Vault"):
        with open(notes_path, "w", encoding="utf-8") as f:
            f.write(new_notes)
        st.success("Appunti salvati permanentemente.")

# ==========================================
# TAB 5: CARTELLE (Saved Research)
# ==========================================
with tab_folders:
    st.header("Archivio Ricerche (Saved Research)")
    st.markdown("Sfoglia i dossier generati in precedenza dalla War Room.")
    
    research_dir = "saved_research"
    if not os.path.exists(research_dir):
        os.makedirs(research_dir)
        
    files = [f for f in os.listdir(research_dir) if f.endswith(".md")]
    
    if not files:
        st.info("Nessuna ricerca salvata. Avvia un'analisi nella War Room per popolare questa cartella.")
    else:
        # Ordina dal più recente
        files.sort(reverse=True)
        
        selected_file = st.selectbox("Seleziona un dossier salvato:", files)
        
        if selected_file:
            with open(os.path.join(research_dir, selected_file), "r", encoding="utf-8") as f:
                content = f.read()
            st.markdown(f"**Documento: {selected_file}**")
            st.markdown("---")
            st.markdown(content)
