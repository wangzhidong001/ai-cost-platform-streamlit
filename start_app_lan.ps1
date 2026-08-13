$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
python -m streamlit run app.py `
  --server.headless=true `
  --server.address=0.0.0.0 `
  --server.port=8501 `
  --browser.gatherUsageStats=false
