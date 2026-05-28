# Automated Due Diligence & Live Portfolio Analytics Terminal 🚀

An advanced financial analysis dashboard built with Streamlit, integrating live portfolio tracking, geographic asset exposure, automated due diligence reports, and multi-agent AI workflows.

## Features
- **Portfolio Live Tracker (Tab 3):** Manage your portfolio (stocks, ETFs, indices) dynamically. Automatically fetches live price data using `yfinance` and calculates real-time metrics (Total Value, P&L, Allocation).
- **Geographic Exposure Map:** Interactive geographic world map (Plotly) visualizing your live portfolio exposure across countries, correctly mapping standard equities as well as ETFs/indices.
- **Multi-Agent Due Diligence (CrewAI):** Execute automated deep research, news sentiment scraping, and financial modeling utilizing AI agents.
- **Persistence:** Local portfolio data is securely saved in `portfolio.json`.

---

## Getting Started

### Prerequisites
- Python 3.10 or higher.
- An LLM API key (e.g., OpenAI or DeepSeek).

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/k6vvk7jssx-png/multy-agent-hedge-found-terminal-.git
   cd multy-agent-hedge-found-terminal-
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Configuration

1. Create a `.env` file in the root directory. You can copy the example file:
   ```bash
   cp .env.example .env
   ```
2. Open the `.env` file and insert your API keys and configuration:
   ```env
   OPENAI_API_KEY=your_openai_api_key
   DEEPSEEK_API_KEY=your_deepseek_api_key
   # Add any other configuration details required by the agents
   ```

### Running the Application

Start the Streamlit server locally:
```bash
streamlit run app.py
```
Open your browser and navigate to the local URL provided (typically `http://localhost:8501` or `http://localhost:8504`).

---

## Security & Privacy
- **Secrets Protection:** The `.env` file containing API keys and private configurations is listed in `.gitignore` and is **never** pushed to the repository.
- **Data Protection:** Personal asset lists stored in `portfolio.json` are excluded from the repository by `.gitignore` to preserve your financial privacy.
- **Hosting:** When deploying to Streamlit Community Cloud, enter your API keys inside the platform's secure **Secrets Manager** dashboard rather than uploading them.
