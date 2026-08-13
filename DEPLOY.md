# Deployment

## Local LAN

Run the app:

```powershell
python -m streamlit run app.py --server.address=0.0.0.0 --server.port=8501
```

Allow Windows Firewall inbound TCP 8501 once, from an Administrator PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\allow_streamlit_8501_admin.ps1
```

Then open:

```text
http://<host-ip>:8501
```

## Demo Data

```powershell
python seed_demo_data.py
python verify_demo_data.py
```

The SQLite database is intentionally not committed. It is created automatically on first run.
