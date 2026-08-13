from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app import DB_PATH, hash_password, month_start


BATCH_ID = "demo-100-v1"

MODEL_BY_TOOL = {
    "飞书 AI": ["Feishu Assistant", "Feishu Minutes", "Feishu Docs AI"],
    "WorkBuddy/CodeBuddy": ["CodeBuddy Pro", "WorkBuddy Agent", "Code Review Bot"],
    "ChatGPT Team": ["GPT-4.1", "GPT-4o", "o3"],
    "Claude Team": ["Claude 3.5 Sonnet", "Claude 3 Opus", "Claude Code"],
    "Trae": ["Trae Builder", "Trae Agent"],
    "FastGPT": ["FastGPT Workflow", "FastGPT Knowledge QA"],
    "UniAPI": ["DeepSeek-V3", "Qwen-Max", "GLM-4.5"],
    "DeepSeek API": ["DeepSeek-R1", "DeepSeek-Coder", "DeepSeek-V3"],
}


DEMO_USERS = [
    ("tech_mgr", "技术中心主管", "manager", "TECH"),
    ("prod_mgr", "产品中心主管", "manager", "PROD"),
    ("ops_mgr", "运营中心主管", "manager", "OPS"),
    ("mkt_mgr", "市场中心主管", "manager", "MKT"),
    ("fin_mgr", "财务部主管", "manager", "FIN"),
    ("tech_alice", "周艾琳", "employee", "TECH"),
    ("tech_bob", "王博", "employee", "TECH"),
    ("tech_cindy", "赵晨", "employee", "TECH"),
    ("prod_dan", "邓远", "employee", "PROD"),
    ("prod_ella", "employee", "employee", "PROD"),
    ("prod_felix", "冯立", "employee", "PROD"),
    ("ops_gina", "高宁", "employee", "OPS"),
    ("ops_henry", "何予", "employee", "OPS"),
    ("ops_iris", "尹然", "employee", "OPS"),
    ("mkt_jack", "蒋骏", "employee", "MKT"),
    ("mkt_kate", "柯婷", "employee", "MKT"),
    ("mkt_louis", "刘思", "employee", "MKT"),
    ("fin_mia", "孟雅", "employee", "FIN"),
    ("fin_noah", "倪浩", "employee", "FIN"),
    ("fin_olivia", "欧阳莉", "employee", "FIN"),
]

DEPT_ANNUAL_BUDGET = {
    "TECH": 36000,  # current month deliberately over budget
    "PROD": 54000,
    "OPS": 66000,
    "MKT": 42000,
    "FIN": 96000,
}

DEPT_MULTIPLIER = {
    "TECH": 1.55,
    "PROD": 0.95,
    "OPS": 0.72,
    "MKT": 1.18,
    "FIN": 0.45,
}


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_supporting_data(conn: sqlite3.Connection) -> None:
    departments = {row["code"]: row for row in conn.execute("SELECT * FROM departments")}
    for code, annual_budget in DEPT_ANNUAL_BUDGET.items():
        dept_id = departments[code]["id"]
        conn.execute(
            """
            INSERT INTO department_budgets(department_id, year, annual_budget)
            VALUES (?, ?, ?)
            ON CONFLICT(department_id, year) DO UPDATE SET annual_budget=excluded.annual_budget
            """,
            (dept_id, date.today().year, annual_budget),
        )

    for username, display_name, role, dept_code in DEMO_USERS:
        dept_id = departments[dept_code]["id"]
        conn.execute(
            """
            INSERT INTO users(username, password_hash, display_name, email, department_id, role, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(username) DO UPDATE SET
                display_name=excluded.display_name,
                department_id=excluded.department_id,
                role=excluded.role,
                status='active'
            """,
            (
                username,
                hash_password("demo123"),
                display_name,
                f"{username}@company.com",
                dept_id,
                role,
            ),
        )

    for username, _, role, dept_code in DEMO_USERS:
        if role == "manager":
            manager_id = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
            conn.execute("UPDATE departments SET manager_id=? WHERE code=?", (manager_id, dept_code))


def clean_old_demo(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM consumption_records WHERE import_batch_id=?", (BATCH_ID,))
    conn.execute("DELETE FROM quota_applications WHERE reason LIKE '演示数据:%'")
    conn.execute("DELETE FROM alerts WHERE title LIKE '演示数据:%'")
    conn.execute("DELETE FROM audit_logs WHERE entity_id=?", (BATCH_ID,))


def seed_budgets(conn: sqlite3.Connection) -> None:
    current_month = month_start()
    tool_rows = list(conn.execute("SELECT id, name FROM tools ORDER BY id"))
    employee_rows = list(conn.execute("SELECT id, username, department_id FROM users WHERE role='employee'"))
    for employee in employee_rows:
        base = 600 if employee["username"].startswith("mkt_") else 900
        if employee["username"].startswith("tech_") or employee["username"] == "employee":
            base = 700
        for idx, tool in enumerate(tool_rows):
            quota = base + (idx % 4) * 140
            conn.execute(
                """
                INSERT INTO user_budgets(user_id, tool_id, month, monthly_quota)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, tool_id, month) DO UPDATE SET monthly_quota=excluded.monthly_quota
                """,
                (employee["id"], tool["id"], current_month, quota),
            )


def seed_consumption(conn: sqlite3.Connection) -> None:
    today = date.today()
    first_day = today.replace(day=1)
    users = list(
        conn.execute(
            """
            SELECT u.id, u.username, u.display_name, d.code AS dept_code, u.department_id
            FROM users u
            JOIN departments d ON d.id=u.department_id
            WHERE u.role='employee'
            ORDER BY d.code, u.username
            """
        )
    )
    tools = list(conn.execute("SELECT id, name, billing_type FROM tools ORDER BY id"))
    inserted = 0

    for i in range(100):
        user = users[i % len(users)]
        tool = tools[(i * 3 + i // 7) % len(tools)]
        models = MODEL_BY_TOOL[tool["name"]]
        model_name = models[(i + user["id"]) % len(models)]
        dept_factor = DEPT_MULTIPLIER[user["dept_code"]]
        base = 58 + (i % 9) * 24 + (tool["id"] % 5) * 35
        cost = round(base * dept_factor, 2)
        if user["dept_code"] == "TECH" and i % 4 == 0:
            cost = round(cost * 2.7, 2)
        if user["dept_code"] == "MKT" and i % 5 == 0:
            cost = round(cost * 2.1, 2)

        record_date = first_day + timedelta(days=(i * 2) % min(today.day, 27))
        if i >= 78:
            previous_month = first_day - timedelta(days=15)
            record_date = previous_month.replace(day=((i * 3) % 24) + 1)

        tokens_input = 0 if tool["billing_type"] in {"seat", "credit"} else 12000 + i * 430
        tokens_output = 0 if tool["billing_type"] in {"seat", "credit"} else 5200 + i * 260
        api_calls = 0 if tool["billing_type"] == "seat" else 8 + i % 37
        credits_used = round(cost / 0.12, 2) if tool["billing_type"] == "credit" else 0
        seat_count = 1 if tool["billing_type"] == "seat" else 0

        conn.execute(
            """
            INSERT INTO consumption_records(
                user_id, department_id, tool_id, model_name, record_date,
                tokens_input, tokens_output, api_calls, credits_used,
                cost_original, currency, cost_cny, billing_type, seat_count,
                is_overage, import_batch_id, source, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, ?, ?, 'import', ?)
            """,
            (
                user["id"],
                user["department_id"],
                tool["id"],
                model_name,
                record_date.isoformat(),
                tokens_input,
                tokens_output,
                api_calls,
                credits_used,
                cost,
                cost,
                tool["billing_type"],
                seat_count,
                1 if cost > 500 else 0,
                BATCH_ID,
                f"演示数据: {user['display_name']} 使用 {tool['name']} / {model_name}",
            ),
        )
        inserted += 1

    assert inserted == 100


def seed_applications_and_alerts(conn: sqlite3.Connection) -> None:
    current_month = month_start()
    app_specs = [
        ("employee", "Claude Team", 1200, "pending", None, "演示数据: 本月研发验证任务增加，申请 Claude 追加额度。"),
        ("tech_alice", "ChatGPT Team", 900, "approved", 900, "演示数据: 项目文档生成和方案评审，需要追加 ChatGPT Team。"),
        ("mkt_jack", "飞书 AI", 600, "pending", None, "演示数据: 市场活动资料集中生成，申请飞书 AI 额度。"),
        ("prod_dan", "UniAPI", 500, "partial", 300, "演示数据: 产品原型测试需要额外 UniAPI 调用额度。"),
        ("ops_gina", "FastGPT", 700, "rejected", 0, "演示数据: 运营知识库批量生成申请，样例驳回。"),
    ]
    for username, tool_name, amount, status, approved, reason in app_specs:
        user = conn.execute("SELECT id, department_id FROM users WHERE username=?", (username,)).fetchone()
        tool = conn.execute("SELECT id FROM tools WHERE name=?", (tool_name,)).fetchone()
        reviewer = conn.execute(
            "SELECT manager_id FROM departments WHERE id=?",
            (user["department_id"],),
        ).fetchone()["manager_id"]
        conn.execute(
            """
            INSERT INTO quota_applications(
                user_id, department_id, tool_id, month, amount, approved_amount,
                reason, status, reviewer_id, review_comment, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                user["department_id"],
                tool["id"],
                current_month,
                amount,
                approved,
                reason,
                status,
                reviewer if status != "pending" else None,
                "演示审批意见" if status != "pending" else None,
                date.today().isoformat() if status != "pending" else None,
            ),
        )

    alert_specs = [
        ("department", None, "TECH", "critical", "演示数据: 技术中心超预算预警", "技术中心本月使用率超过 100%，请主管复核成员费用和额度申请。"),
        ("department", None, "MKT", "warning", "演示数据: 市场中心预算预警", "市场中心本月使用率超过 80%，建议关注飞书 AI 和 ChatGPT 使用。"),
        ("employee", "employee", None, "warning", "演示数据: 个人额度预警", "你本月多个工具费用接近月度额度，可在额度申请页提交追加申请。"),
        ("employee", "tech_alice", None, "critical", "演示数据: 个人超预算预警", "Claude Team 与 ChatGPT Team 使用较高，已触发 critical 预警。"),
    ]
    for scope, username, dept_code, level, title, message in alert_specs:
        user_id = None
        dept_id = None
        if username:
            row = conn.execute("SELECT id, department_id FROM users WHERE username=?", (username,)).fetchone()
            user_id = row["id"]
            dept_id = row["department_id"]
        if dept_code:
            dept_id = conn.execute("SELECT id FROM departments WHERE code=?", (dept_code,)).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO alerts(scope, user_id, department_id, level, title, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (scope, user_id, dept_id, level, title, message),
        )


def print_summary(conn: sqlite3.Connection) -> None:
    print(f"DB={Path(DB_PATH).resolve()}")
    print("inserted_consumption_records", conn.execute("SELECT COUNT(*) FROM consumption_records WHERE import_batch_id=?", (BATCH_ID,)).fetchone()[0])
    print("demo_users", conn.execute("SELECT COUNT(*) FROM users WHERE username IN (%s)" % ",".join("?" for _ in DEMO_USERS), tuple(u[0] for u in DEMO_USERS)).fetchone()[0])
    print("models", conn.execute("SELECT COUNT(DISTINCT model_name) FROM consumption_records WHERE import_batch_id=?", (BATCH_ID,)).fetchone()[0])
    print("tools", conn.execute("SELECT COUNT(DISTINCT tool_id) FROM consumption_records WHERE import_batch_id=?", (BATCH_ID,)).fetchone()[0])
    print("departments", conn.execute("SELECT COUNT(DISTINCT department_id) FROM consumption_records WHERE import_batch_id=?", (BATCH_ID,)).fetchone()[0])
    for row in conn.execute(
        """
        SELECT d.name,
               ROUND(SUM(c.cost_cny), 2) AS used,
               ROUND(b.annual_budget / 12.0, 2) AS monthly_budget,
               ROUND(SUM(c.cost_cny) / (b.annual_budget / 12.0) * 100, 1) AS usage_pct
        FROM consumption_records c
        JOIN departments d ON d.id=c.department_id
        JOIN department_budgets b ON b.department_id=d.id AND b.year=?
        WHERE c.import_batch_id=? AND substr(c.record_date, 1, 7)=substr(?, 1, 7)
        GROUP BY d.id
        ORDER BY usage_pct DESC
        """,
        (date.today().year, BATCH_ID, month_start()),
    ):
        print(f"dept_usage {row['name']} used={row['used']} monthly_budget={row['monthly_budget']} usage={row['usage_pct']}%")


def main() -> None:
    with connect() as conn:
        upsert_supporting_data(conn)
        clean_old_demo(conn)
        seed_budgets(conn)
        seed_consumption(conn)
        seed_applications_and_alerts(conn)
        conn.execute(
            "INSERT INTO audit_logs(actor_id, action, entity, entity_id, detail) VALUES (NULL, 'seed', 'demo_data', ?, '生成 100 条覆盖角色、部门、工具、模型和预警审批场景的演示数据')",
            (BATCH_ID,),
        )
        conn.commit()
        print_summary(conn)


if __name__ == "__main__":
    main()
