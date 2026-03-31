#!/bin/bash
# ──────────────────────────────────────────────
# 🎬 Arkitect Cinematography Console — Launcher
# by Alessio Valori DOP
# ──────────────────────────────────────────────

# Navigate to the project folder
cd "$(dirname "$0")"

# Launch Streamlit in the background (port 8501)
echo "🚀 Launching Arkitect Cinematography Console..."
nohup streamlit run ui_app.py --server.port 8501 > arkitect_log.txt 2>&1 &

# Wait a moment to let Streamlit start
sleep 3

# Open in default browser
open http://localhost:8501

echo "✅ Arkitect Console is running at http://localhost:8501"
echo "🪶 You can close this terminal safely — Streamlit runs in the background."
