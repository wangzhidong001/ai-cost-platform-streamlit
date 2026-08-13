# Run this script in Windows PowerShell as Administrator.
New-NetFirewallRule `
  -DisplayName "AI Cost Streamlit 8501" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8501 `
  -Profile Any

Write-Host "Firewall rule added: AI Cost Streamlit 8501"
