import sqlite3


def scalar(cur, sql, params=()):
    return cur.execute(sql, params).fetchone()[0]


with sqlite3.connect("data/ai_cost.db") as conn:
    cur = conn.cursor()
    print("demo_records", scalar(cur, "SELECT COUNT(*) FROM consumption_records WHERE import_batch_id=?", ("demo-100-v1",)))
    print("tools", scalar(cur, "SELECT COUNT(DISTINCT tool_id) FROM consumption_records WHERE import_batch_id=?", ("demo-100-v1",)))
    print("models", scalar(cur, "SELECT COUNT(DISTINCT model_name) FROM consumption_records WHERE import_batch_id=?", ("demo-100-v1",)))
    print("departments", scalar(cur, "SELECT COUNT(DISTINCT department_id) FROM consumption_records WHERE import_batch_id=?", ("demo-100-v1",)))
    print("demo_users", scalar(cur, "SELECT COUNT(*) FROM users WHERE username LIKE '%\\_%' ESCAPE '\\' OR username IN ('tech_mgr','prod_mgr','ops_mgr','mkt_mgr','fin_mgr')"))
    print("pending_applications", scalar(cur, "SELECT COUNT(*) FROM quota_applications WHERE status='pending'"))
    print("approved_or_partial", scalar(cur, "SELECT COUNT(*) FROM quota_applications WHERE status IN ('approved','partial')"))
    print("demo_alerts", scalar(cur, "SELECT COUNT(*) FROM alerts WHERE title LIKE '演示数据:%'"))
