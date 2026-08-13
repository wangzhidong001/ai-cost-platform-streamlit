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

## Streamlit Community Cloud

Use these values when creating the app in Streamlit Community Cloud:

- Repository: `wangzhidong001/ai-cost-platform-streamlit`
- Branch: `main`
- Main file path: `app.py`
- Python runtime: `python-3.11` from `runtime.txt`

On first startup, the app creates its SQLite database and automatically seeds the 100-record demo batch unless `AI_COST_AUTO_SEED=0` is set.
