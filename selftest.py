import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AI_COST_DB"] = str(Path(tmp) / "test.db")
        import app

        app.init_db()

        admin = app.authenticate("admin", "admin123")
        manager = app.authenticate("manager", "manager123")
        employee = app.authenticate("employee", "employee123")
        assert admin and admin.role == "admin"
        assert manager and manager.role == "manager"
        assert employee and employee.role == "employee"

        summary = app.get_user_month_summary(employee.id, app.month_start())
        assert summary["quota"] > 0
        assert summary["used"] >= 0

        tool_id = int(app.fetch_df("SELECT id FROM tools LIMIT 1")["id"].iloc[0])
        app.execute(
            """
            INSERT INTO quota_applications(user_id, department_id, tool_id, month, amount, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (employee.id, employee.department_id, tool_id, app.month_start(), 123.0, "端到端测试追加额度申请"),
        )
        app_id = int(app.fetch_df("SELECT MAX(id) AS id FROM quota_applications")["id"].iloc[0])
        app.review_application(app_id, manager, "approved", 123.0, "自测通过")
        reviewed = app.fetch_one("SELECT status, approved_amount FROM quota_applications WHERE id=?", (app_id,))
        assert reviewed["status"] == "approved"
        assert float(reviewed["approved_amount"]) == 123.0

        df = pd.DataFrame(
            [
                {
                    "username": "employee",
                    "tool": "飞书 AI",
                    "record_date": date.today().isoformat(),
                    "cost_cny": 12.34,
                    "tokens_input": 1000,
                    "tokens_output": 500,
                }
            ]
        )
        ok, message, prepared = app.validate_import(df)
        assert ok, message
        batch_id = app.import_consumption(prepared, admin.id)
        assert batch_id.startswith("imp-")
        imported = app.fetch_one(
            "SELECT COUNT(*) AS c FROM consumption_records WHERE import_batch_id=?",
            (batch_id,),
        )
        assert imported["c"] == 1

        assert not app.fetch_df("SELECT * FROM audit_logs").empty
        assert not app.fetch_df("SELECT * FROM alerts").empty

    print("SELFTEST_OK")


if __name__ == "__main__":
    main()
