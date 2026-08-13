import os
from pathlib import Path

os.environ["AI_COST_DB"] = str(Path("data") / "cloud_smoke.db")

import app

app.init_db()
app.ensure_demo_data()
row = app.fetch_one("SELECT COUNT(*) AS c FROM consumption_records WHERE import_batch_id=?", ("demo-100-v1",))
print(f"cloud_demo_records {row['c']}")
