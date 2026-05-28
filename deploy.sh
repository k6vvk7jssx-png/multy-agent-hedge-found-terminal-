#!/bin/bash
# ============================================================
# Automated Due Diligence Terminal - VPS Deployment Script
# Target Architecture: Ubuntu/Debian ARM64 (Hetzner CAX11)
# ============================================================

set -e # Ferma lo script in caso di errori

echo "============================================================"
echo "Avvio deployment ecosistema Due Diligence..."
echo "============================================================"

# 1. Aggiornamento di sistema e patch di sicurezza
echo "[1/5] Aggiornamento indici di sistema e pacchetti..."
sudo apt update && sudo apt upgrade -y

# 2. Installazione toolchain di sistema
echo "[2/5] Installazione Python3, Pip, Git e librerie essenziali..."
sudo apt install -y python3 python3-pip python3-venv git build-essential sqlite3 libsqlite3-dev

# 3. Isolamento Virtual Environment
echo "[3/5] Configurazione Virtual Environment (.venv)..."
python3 -m venv .venv
source .venv/bin/activate

# 4. Installazione Pilastri Architetturali (CrewAI, ChromaDB, ecc.)
echo "[4/5] Installazione dipendenze Python..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Demone Systemd per esecuzione continua 24/7 (Stealth Mode)
echo "[5/5] Configurazione servizio systemd (Auto-restart al riavvio)..."
SERVICE_FILE="/etc/systemd/system/duediligence.service"
APP_DIR=$(pwd)
CURRENT_USER=$(whoami)

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Automated Due Diligence Terminal (Streamlit + CrewAI)
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/.venv/bin"
ExecStart=$APP_DIR/.venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Ricarica e avvia il servizio
sudo systemctl daemon-reload
sudo systemctl enable duediligence
sudo systemctl restart duediligence

echo "============================================================"
echo "✅ DEPLOYMENT COMPLETATO CON SUCCESSO!"
echo "Il Terminale Streamlit è online e blindato in background via Systemd."
echo ""
echo "Per accedere all'interfaccia:"
echo "http://<IP_DEL_SERVER>:8501"
echo ""
echo "Per monitorare il flusso di pensiero degli agenti CrewAI nei log:"
echo "sudo journalctl -u duediligence -f"
echo "============================================================"
