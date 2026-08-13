from __future__ import annotations

import hashlib
import base64
import io
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st


APP_TITLE = "锐捷AI费用管理系统"
DB_PATH = Path(os.getenv("AI_COST_DB", "data/ai_cost.db"))
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
LOGO_PATH = Path("assets/ruijie_logo.svg")
PAGE_SIZE = 50

BILLING_TYPE_LABELS = {
    "seat": "席位月租",
    "usage": "按量计费",
    "hybrid": "混合计费",
    "credit": "积分计费",
}
STATUS_LABELS = {
    "active": "启用",
    "inactive": "停用",
    "pending": "待审批",
    "approved": "已通过",
    "partial": "部分通过",
    "rejected": "已驳回",
}
ROLE_LABELS = {"employee": "员工", "manager": "部门主管", "admin": "预算管理员"}
SOURCE_LABELS = {"manual": "手工录入", "import": "导入", "api": "接口同步"}
LEVEL_LABELS = {"warning": "预警", "critical": "严重"}
SCOPE_LABELS = {"employee": "员工", "department": "部门", "company": "公司"}
ACTION_LABELS = {
    "login": "登录",
    "create": "新增",
    "upsert": "新增/更新",
    "import": "导入",
    "seed": "演示造数",
    "seed_failed": "演示造数失败",
    "approved": "审批通过",
    "partial": "部分通过",
    "rejected": "驳回",
}
ENTITY_LABELS = {
    "session": "会话",
    "quota_application": "额度申请",
    "user_budget": "员工额度",
    "department_budget": "部门预算",
    "consumption_records": "消费记录",
    "demo_data": "演示数据",
    "user": "用户",
    "tool": "工具",
}
COLUMN_LABELS = {
    "username": "用户名",
    "tool": "工具",
    "record_date": "消费日期",
    "cost_cny": "人民币费用",
    "model_name": "模型",
    "tokens_input": "输入 Token",
    "tokens_output": "输出 Token",
    "api_calls": "接口调用次数",
    "currency": "币种",
    "billing_type": "计费类型",
    "notes": "备注",
}


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str
    department_id: int | None
    department_name: str | None


def month_start(value: date | None = None) -> str:
    value = value or date.today()
    return value.replace(day=1).isoformat()


def add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    return date(year, month, 1)


def local_now() -> datetime:
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def local_now_text() -> str:
    return local_now().strftime("%Y-%m-%d %H:%M:%S")


def logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def hash_password(password: str) -> str:
    salt = "ai-cost-platform-v1"
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


@contextmanager
def get_conn() -> Any:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with get_conn() as conn:
        conn.execute(sql, params)


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()


def fetch_df(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT NOT NULL UNIQUE,
                manager_id INTEGER,
                status TEXT NOT NULL DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                email TEXT,
                employee_id TEXT,
                department_id INTEGER,
                role TEXT NOT NULL CHECK(role IN ('employee','manager','admin')),
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(department_id) REFERENCES departments(id)
            );

            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                billing_type TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                unit_price REAL NOT NULL DEFAULT 0,
                monthly_seat_price REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS consumption_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_id INTEGER,
                tool_id INTEGER NOT NULL,
                model_name TEXT,
                record_date TEXT NOT NULL,
                tokens_input INTEGER NOT NULL DEFAULT 0,
                tokens_output INTEGER NOT NULL DEFAULT 0,
                api_calls INTEGER NOT NULL DEFAULT 0,
                credits_used REAL NOT NULL DEFAULT 0,
                cost_original REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'CNY',
                cost_cny REAL NOT NULL DEFAULT 0,
                billing_type TEXT,
                seat_count INTEGER NOT NULL DEFAULT 0,
                is_overage INTEGER NOT NULL DEFAULT 0,
                import_batch_id TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(department_id) REFERENCES departments(id),
                FOREIGN KEY(tool_id) REFERENCES tools(id)
            );

            CREATE TABLE IF NOT EXISTS user_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tool_id INTEGER,
                month TEXT NOT NULL,
                monthly_quota REAL NOT NULL DEFAULT 0,
                UNIQUE(user_id, tool_id, month),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(tool_id) REFERENCES tools(id)
            );

            CREATE TABLE IF NOT EXISTS department_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                annual_budget REAL NOT NULL DEFAULT 0,
                UNIQUE(department_id, year),
                FOREIGN KEY(department_id) REFERENCES departments(id)
            );

            CREATE TABLE IF NOT EXISTS quota_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_id INTEGER,
                tool_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                amount REAL NOT NULL,
                approved_amount REAL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_id INTEGER,
                review_comment TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(tool_id) REFERENCES tools(id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                user_id INTEGER,
                department_id INTEGER,
                level TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER,
                action TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id TEXT,
                detail TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        existing = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if existing:
            return

        departments = [
            ("技术中心", "TECH"),
            ("产品中心", "PROD"),
            ("运营中心", "OPS"),
            ("市场中心", "MKT"),
            ("财务部", "FIN"),
        ]
        conn.executemany("INSERT INTO departments(name, code) VALUES (?, ?)", departments)

        dept_ids = {
            row["code"]: row["id"]
            for row in conn.execute("SELECT id, code FROM departments").fetchall()
        }
        users = [
            ("admin", hash_password("admin123"), "系统管理员", "admin@company.com", None, "admin"),
            ("manager", hash_password("manager123"), "技术主管", "manager@company.com", dept_ids["TECH"], "manager"),
            ("employee", hash_password("employee123"), "张晓明", "employee@company.com", dept_ids["TECH"], "employee"),
            ("chenyu", hash_password("employee123"), "陈雨", "chenyu@company.com", dept_ids["TECH"], "employee"),
            ("lina", hash_password("employee123"), "李娜", "lina@company.com", dept_ids["PROD"], "employee"),
        ]
        conn.executemany(
            """
            INSERT INTO users(username, password_hash, display_name, email, department_id, role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            users,
        )
        manager_id = conn.execute("SELECT id FROM users WHERE username='manager'").fetchone()["id"]
        conn.execute("UPDATE departments SET manager_id=? WHERE code='TECH'", (manager_id,))

        tools = [
            ("飞书 AI", "hybrid", "CNY", 0.00018, 98),
            ("WorkBuddy/CodeBuddy", "seat", "CNY", 0, 299),
            ("ChatGPT Team", "seat", "USD", 0, 25),
            ("Claude Team", "usage", "USD", 0.00021, 0),
            ("Trae", "credit", "CNY", 0.12, 0),
            ("FastGPT", "usage", "CNY", 0.00009, 0),
            ("UniAPI", "usage", "CNY", 0.00012, 0),
            ("DeepSeek API", "usage", "CNY", 0.00002, 0),
        ]
        conn.executemany(
            "INSERT INTO tools(name, billing_type, currency, unit_price, monthly_seat_price) VALUES (?, ?, ?, ?, ?)",
            tools,
        )

        for dept_id in dept_ids.values():
            conn.execute(
                "INSERT INTO department_budgets(department_id, year, annual_budget) VALUES (?, ?, ?)",
                (dept_id, date.today().year, 180000 if dept_id == dept_ids["TECH"] else 90000),
            )

        employee_rows = conn.execute(
            "SELECT id, department_id FROM users WHERE role='employee'"
        ).fetchall()
        tool_rows = conn.execute("SELECT id, name, billing_type FROM tools").fetchall()
        current_month = date.today().replace(day=1)
        for employee in employee_rows:
            for tool in tool_rows[:5]:
                conn.execute(
                    """
                    INSERT INTO user_budgets(user_id, tool_id, month, monthly_quota)
                    VALUES (?, ?, ?, ?)
                    """,
                    (employee["id"], tool["id"], current_month.isoformat(), 2500),
                )

        batch_id = f"seed-{uuid.uuid4().hex[:8]}"
        for offset in range(-5, 1):
            record_month = add_months(current_month, offset)
            for employee in employee_rows:
                for idx, tool in enumerate(tool_rows[:6], start=1):
                    value = 120 + idx * 38 + (employee["id"] % 3) * 50 + max(offset + 5, 0) * 18
                    conn.execute(
                        """
                        INSERT INTO consumption_records(
                            user_id, department_id, tool_id, model_name, record_date,
                            tokens_input, tokens_output, api_calls, cost_original, currency,
                            cost_cny, billing_type, seat_count, import_batch_id, source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'import')
                        """,
                        (
                            employee["id"],
                            employee["department_id"],
                            tool["id"],
                            "默认模型",
                            (record_month + timedelta(days=min(idx * 3, 25))).isoformat(),
                            30000 * idx,
                            12000 * idx,
                            20 * idx,
                            value,
                            "CNY",
                            value,
                            tool["billing_type"],
                            1 if tool["billing_type"] == "seat" else 0,
                            batch_id,
                        ),
                    )

        employee_id = conn.execute("SELECT id FROM users WHERE username='employee'").fetchone()["id"]
        tool_id = conn.execute("SELECT id FROM tools WHERE name='Claude Team'").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO quota_applications(user_id, department_id, tool_id, month, amount, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (employee_id, dept_ids["TECH"], tool_id, current_month.isoformat(), 800, "本月研发任务增加，需要追加 Claude Team 调试额度。", local_now_text()),
        )
        conn.execute(
            """
            INSERT INTO alerts(scope, user_id, department_id, level, title, message)
            VALUES ('employee', ?, ?, 'warning', '个人额度使用率较高', '本月 AI 工具费用已接近预算阈值，请关注后续使用。')
            """,
            (employee_id, dept_ids["TECH"]),
        )


def ensure_demo_data() -> None:
    if os.getenv("AI_COST_AUTO_SEED", "1") != "1":
        return
    existing = fetch_one(
        "SELECT COUNT(*) AS c FROM consumption_records WHERE import_batch_id='demo-100-v1'"
    )
    if existing and existing["c"]:
        return
    try:
        import seed_demo_data

        seed_demo_data.main()
    except Exception as exc:
        add_audit(None, "seed_failed", "demo_data", "demo-100-v1", str(exc))


def add_audit(actor_id: int | None, action: str, entity: str, entity_id: str, detail: str) -> None:
    execute(
        "INSERT INTO audit_logs(actor_id, action, entity, entity_id, detail) VALUES (?, ?, ?, ?, ?)",
        (actor_id, action, entity, entity_id, detail),
    )


def authenticate(username: str, password: str) -> User | None:
    row = fetch_one(
        """
        SELECT u.*, d.name AS department_name
        FROM users u
        LEFT JOIN departments d ON d.id = u.department_id
        WHERE u.username=? AND u.status='active'
        """,
        (username.strip(),),
    )
    if not row or row["password_hash"] != hash_password(password):
        return None
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        department_id=row["department_id"],
        department_name=row["department_name"],
    )


def get_current_user() -> User | None:
    raw = st.session_state.get("user")
    if not raw:
        return None
    return User(**raw)


def set_current_user(user: User) -> None:
    st.session_state["user"] = user.__dict__


def require_role(user: User, roles: set[str]) -> bool:
    if user.role not in roles:
        st.error("当前账号无权访问该页面。")
        return False
    return True


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --brand: #1d4ed8;
          --brand-soft: #eff6ff;
          --ink: #0f172a;
          --muted: #64748b;
          --line: #e2e8f0;
          --surface: #ffffff;
          --surface-soft: #f8fafc;
        }
        .stApp { background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); }
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1280px; }
        section[data-testid="stSidebar"] {
          background: #0f172a;
          border-right: 1px solid rgba(255, 255, 255, 0.08);
        }
        section[data-testid="stSidebar"] * { color: #e5e7eb !important; }
        section[data-testid="stSidebar"] [role="radiogroup"] label {
          border-radius: 8px;
          padding: 6px 8px;
        }
        h1, h2, h3 { color: var(--ink); letter-spacing: 0; }
        h1 { font-size: 2rem; }
        h2 { font-size: 1.45rem; }
        h3 { font-size: 1.08rem; }
        [data-testid="stMetric"] {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 8px;
          padding: 16px 18px;
          box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
        }
        [data-testid="stMetricLabel"] p { color: var(--muted); }
        [data-testid="stMetricValue"] { color: var(--ink); }
        div[data-testid="stDataFrame"] {
          border: 1px solid var(--line);
          border-radius: 8px;
          overflow: hidden;
        }
        .hero {
          background: radial-gradient(circle at 20% 10%, rgba(125, 211, 252, 0.42), transparent 30%),
                      linear-gradient(145deg, #1e40af 0%, #0284c7 48%, #38bdf8 100%);
          border-radius: 0;
          padding: 38px 46px;
          color: #fff;
          min-height: 620px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          position: relative;
          overflow: hidden;
          box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
        }
        .hero:before {
          content: "";
          position: absolute;
          inset: auto -80px -120px -80px;
          height: 260px;
          background: rgba(255,255,255,0.16);
          transform: rotate(-7deg);
        }
        .hero h1 { color: #fff; font-size: 2.4rem; margin: 0 0 12px; }
        .hero p { color: #dbeafe; font-size: 1rem; line-height: 1.7; }
        .login-logo { width: 157px; height: 27px; margin-bottom: 18px; object-fit: contain; }
        .login-subtitle { font-size: 0.9rem; color: rgba(255,255,255,0.86); letter-spacing: 0; }
        .login-illustration {
          width: min(430px, 90%);
          min-height: 250px;
          margin: 32px auto 12px;
          position: relative;
        }
        .platform {
          position: absolute;
          left: 50%;
          top: 118px;
          width: 250px;
          height: 150px;
          background: linear-gradient(145deg, #e0f2fe, #ffffff);
          border-radius: 26px;
          transform: translateX(-50%) rotateX(58deg) rotateZ(-34deg);
          box-shadow: 0 28px 58px rgba(15, 23, 42, 0.22);
        }
        .door {
          position: absolute;
          left: 50%;
          top: 50px;
          width: 110px;
          height: 150px;
          transform: translateX(-50%);
          background: linear-gradient(160deg, #ffffff, #bfdbfe);
          border: 5px solid rgba(255,255,255,0.72);
          border-radius: 16px;
          box-shadow: 0 20px 42px rgba(15, 23, 42, 0.20);
        }
        .door:after {
          content: "";
          position: absolute;
          right: 18px;
          top: 70px;
          width: 10px;
          height: 10px;
          background: #2563eb;
          border-radius: 50%;
        }
        .ai-tile {
          position: absolute;
          width: 70px;
          height: 54px;
          border-radius: 12px;
          color: #fff;
          font-weight: 700;
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 16px 30px rgba(15, 23, 42, 0.20);
        }
        .tile-1 { left: 42px; top: 32px; background: #8b5cf6; transform: rotate(-18deg); }
        .tile-2 { right: 48px; top: 60px; background: #f43f5e; transform: rotate(12deg); }
        .tile-3 { left: 4px; top: 128px; background: #facc15; transform: rotate(10deg); }
        .cloud-dot {
          position: absolute;
          width: 52px;
          height: 24px;
          border-radius: 999px;
          background: rgba(255,255,255,0.72);
          box-shadow: 70px 54px 0 rgba(255,255,255,0.34), 230px 32px 0 rgba(255,255,255,0.34);
          left: 104px;
          top: 48px;
        }
        .hero-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 10px;
          margin-top: 24px;
        }
        .hero-stat {
          background: rgba(255, 255, 255, 0.12);
          border: 1px solid rgba(255, 255, 255, 0.18);
          border-radius: 8px;
          padding: 12px;
        }
        .hero-stat strong { display: block; font-size: 1.25rem; color: #fff; }
        .hero-stat span { color: #bfdbfe; font-size: 0.84rem; }
        .login-panel-title { text-align: left; font-size: 1.42rem; font-weight: 800; color: #0f172a; margin: 8px 0 8px; }
        .login-form-shell {
          background: #ffffff;
          border: 1px solid var(--line);
          border-radius: 14px;
          padding: 18px 20px;
          margin-top: 42px;
          box-shadow: 0 18px 42px rgba(15, 23, 42, 0.10);
        }
        .login-form-shell img { width: 157px; height: 27px; object-fit: contain; margin-bottom: 8px; }
        div[data-testid="stForm"] .stButton > button {
          background: #1263f1;
          color: #fff;
          border: none;
          border-radius: 6px;
          height: 42px;
          font-weight: 700;
        }
        div[data-testid="stForm"] .stButton > button:hover { background: #0f56d8; color: #fff; }
        .login-page-note { color: #64748b; font-size: 0.88rem; margin-bottom: 14px; }
        .demo-title { margin-top: 18px; color: #334155; font-weight: 700; }
        @media (max-width: 900px) {
          .hero { min-height: 420px; padding: 28px; }
        }
        .section-card {
          background: rgba(255, 255, 255, 0.76);
          border: 1px solid var(--line);
          border-radius: 10px;
          padding: 16px 18px;
          margin: 10px 0 14px;
        }
        .status-pill {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 999px;
          font-size: 12px;
          border: 1px solid rgba(148, 163, 184, 0.36);
        }
        .hint { color: var(--muted); font-size: 13px; }
        .small-label { color: var(--muted); font-size: 0.86rem; margin-bottom: 4px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_money(value: float | int | None) -> str:
    return f"¥{float(value or 0):,.2f}"


def label_value(value: Any, mapping: dict[str, str]) -> Any:
    return mapping.get(str(value), value)


def localize_df(df: pd.DataFrame) -> pd.DataFrame:
    localized = df.copy()
    mapping_by_column = {
        "计费类型": BILLING_TYPE_LABELS,
        "状态": STATUS_LABELS,
        "角色": ROLE_LABELS,
        "来源": SOURCE_LABELS,
        "级别": LEVEL_LABELS,
        "范围": SCOPE_LABELS,
        "动作": ACTION_LABELS,
        "对象": ENTITY_LABELS,
        "billing_type": BILLING_TYPE_LABELS,
    }
    for column, mapping in mapping_by_column.items():
        if column in localized.columns:
            localized[column] = localized[column].map(lambda value: label_value(value, mapping))
    localized = localized.rename(columns=COLUMN_LABELS)
    return localized


def to_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="data")
    return output.getvalue()


def get_import_template() -> bytes:
    template = pd.DataFrame(
        [
            {
                "username": "employee",
                "tool": "飞书 AI",
                "record_date": date.today().isoformat(),
                "cost_cny": 128.50,
                "model_name": "Feishu Assistant",
                "tokens_input": 12000,
                "tokens_output": 4800,
                "api_calls": 18,
                "currency": "CNY",
                "billing_type": "hybrid",
                "notes": "模板样例：请按实际消费替换本行",
            },
            {
                "username": "tech_alice",
                "tool": "Claude Team",
                "record_date": date.today().isoformat(),
                "cost_cny": 260.00,
                "model_name": "Claude 3.5 Sonnet",
                "tokens_input": 25000,
                "tokens_output": 9600,
                "api_calls": 24,
                "currency": "CNY",
                "billing_type": "usage",
                "notes": "可删除样例行后上传",
            },
        ]
    )
    return to_excel(template)


def get_user_month_summary(user_id: int, month: str) -> dict[str, float]:
    row = fetch_one(
        """
        SELECT
          COALESCE(SUM(c.cost_cny), 0) AS used,
          COALESCE((SELECT SUM(monthly_quota) FROM user_budgets WHERE user_id=? AND month=?), 0) AS quota
        FROM consumption_records c
        WHERE c.user_id=? AND substr(c.record_date, 1, 7)=substr(?, 1, 7)
        """,
        (user_id, month, user_id, month),
    )
    used = float(row["used"] if row else 0)
    quota = float(row["quota"] if row else 0)
    return {"used": used, "quota": quota, "remaining": max(quota - used, 0), "usage": used / quota if quota else 0}


def get_department_month_summary(department_id: int, month: str) -> dict[str, float]:
    row = fetch_one(
        """
        SELECT COALESCE(SUM(cost_cny), 0) AS used
        FROM consumption_records
        WHERE department_id=? AND substr(record_date, 1, 7)=substr(?, 1, 7)
        """,
        (department_id, month),
    )
    budget = fetch_one(
        "SELECT annual_budget FROM department_budgets WHERE department_id=? AND year=?",
        (department_id, date.fromisoformat(month).year),
    )
    annual = float(budget["annual_budget"] if budget else 0)
    monthly = annual / 12 if annual else 0
    used = float(row["used"] if row else 0)
    return {"used": used, "quota": monthly, "remaining": max(monthly - used, 0), "usage": used / monthly if monthly else 0}


def render_login() -> None:
    logo_uri = logo_data_uri()
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        st.markdown(
            f"""
            <div class="hero">
              <div>
                <img class="login-logo" src="{logo_uri}" alt="Ruijie Networks" />
                <div class="login-subtitle">Ruijie AI Cost Management System</div>
                <h1>锐捷AI费用管理系统</h1>
                <p>统一管理 AI 工具费用、预算执行、额度审批和超支预警，支持员工、部门主管和预算管理员分角色查看。</p>
                <div class="login-illustration">
                  <div class="cloud-dot"></div>
                  <div class="ai-tile tile-1">AI</div>
                  <div class="ai-tile tile-2">费用</div>
                  <div class="ai-tile tile-3">预算</div>
                  <div class="platform"></div>
                  <div class="door"></div>
                </div>
              </div>
              <div class="hero-grid">
                <div class="hero-stat"><strong>8 类</strong><span>AI 工具费率</span></div>
                <div class="hero-stat"><strong>100+</strong><span>演示消费记录</span></div>
                <div class="hero-stat"><strong>7×24</strong><span>支持在线部署</span></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"""
            <div class="login-form-shell">
              <img src="{logo_uri}" alt="Ruijie Networks" />
              <div class="login-panel-title">账号登录</div>
              <div class="login-page-note">请输入企业账号，系统将按角色展示对应看板</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            username = st.text_input("用户名", value="admin")
            password = st.text_input("密码", value="admin123", type="password")
            submitted = st.form_submit_button("登录", use_container_width=True)
        if submitted:
            user = authenticate(username, password)
            if user:
                set_current_user(user)
                add_audit(user.id, "login", "session", str(user.id), "用户登录")
                st.rerun()
            st.error("用户名或密码错误，或账号已停用。")
        st.markdown('<div class="demo-title">演示账号</div>', unsafe_allow_html=True)
        st.dataframe(
            pd.DataFrame(
                [
                    {"角色": "管理员", "用户名": "admin", "密码": "admin123"},
                    {"角色": "主管", "用户名": "manager", "密码": "manager123"},
                    {"角色": "员工", "用户名": "employee", "密码": "employee123"},
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )


def render_sidebar(user: User) -> str:
    st.sidebar.title(APP_TITLE)
    st.sidebar.caption(f"{user.display_name} · {role_label(user.role)}")
    if user.department_name:
        st.sidebar.caption(user.department_name)
    pages = {
        "employee": ["个人仪表盘", "消费明细", "额度申请", "预警通知", "工具费率"],
        "manager": ["部门仪表盘", "成员明细", "额度审批", "部门预算分配", "部门报表"],
        "admin": ["公司总览", "数据导入", "预算管理", "用户管理", "工具管理", "预警中心", "审计日志"],
    }[user.role]
    page = st.sidebar.radio("导航", pages)
    if st.sidebar.button("退出登录", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    return page


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def usage_status(usage: float) -> tuple[str, str]:
    if usage >= 1:
        return "严重超支", "critical"
    if usage >= 0.9:
        return "接近超支", "warning"
    if usage >= 0.8:
        return "偏高", "warning"
    return "正常", "normal"


def render_analysis_box(title: str, lines: list[str], level: str = "normal") -> None:
    content = "\n".join(f"- {line}" for line in lines)
    if level == "critical":
        st.error(f"**{title}**\n\n{content}")
    elif level == "warning":
        st.warning(f"**{title}**\n\n{content}")
    else:
        st.info(f"**{title}**\n\n{content}")


def render_employee_analysis(user: User, summary: dict[str, float], quota_df: pd.DataFrame) -> None:
    status, level = usage_status(summary["usage"])
    lines = [
        f"本月预算执行状态为 **{status}**：已用 {format_money(summary['used'])}，月度额度 {format_money(summary['quota'])}，剩余 {format_money(summary['remaining'])}，整体使用率 {summary['usage']:.1%}。",
    ]
    if quota_df.empty:
        lines.append("当前未配置工具级额度，建议联系主管先完成月度额度分配。")
    else:
        over_df = quota_df[quota_df["使用率"] >= 1].sort_values("使用率", ascending=False)
        warn_df = quota_df[(quota_df["使用率"] >= 0.8) & (quota_df["使用率"] < 1)].sort_values("使用率", ascending=False)
        if not over_df.empty:
            row = over_df.iloc[0]
            lines.append(f"重点关注工具是 **{row['工具']}**，已用 {format_money(row['已用费用'])}，额度 {format_money(row['月度额度'])}，使用率 {row['使用率']:.1%}，已超出预算。")
        elif not warn_df.empty:
            row = warn_df.iloc[0]
            lines.append(f"最接近超支的工具是 **{row['工具']}**，使用率 {row['使用率']:.1%}，建议提前评估是否需要申请追加额度。")
        else:
            top = quota_df.sort_values("已用费用", ascending=False).iloc[0]
            lines.append(f"当前费用最高的工具是 **{top['工具']}**，已用 {format_money(top['已用费用'])}，预算执行整体可控。")

    model_df = fetch_df(
        """
        SELECT COALESCE(c.model_name, t.name) AS 模型, t.name AS 工具, SUM(c.cost_cny) AS 费用
        FROM consumption_records c
        JOIN tools t ON t.id=c.tool_id
        WHERE c.user_id=? AND substr(c.record_date, 1, 7)=substr(?, 1, 7)
        GROUP BY COALESCE(c.model_name, t.name), t.name
        ORDER BY 费用 DESC
        LIMIT 1
        """,
        (user.id, month_start()),
    )
    if not model_df.empty:
        row = model_df.iloc[0]
        lines.append(f"模型费用最高的是 **{row['模型']}**（{row['工具']}），本月费用 {format_money(row['费用'])}，后续使用应优先关注该模型。")
    if summary["usage"] >= 0.8:
        lines.append("建议动作：在“额度申请”页提交追加额度，或压降高费用模型/工具的非必要调用。")
    render_analysis_box("分析说明", lines, level)


def render_manager_analysis(user: User, summary: dict[str, float], model_df: pd.DataFrame) -> None:
    status, level = usage_status(summary["usage"])
    lines = [
        f"{user.department_name or '本部门'} 本月预算执行状态为 **{status}**：已用 {format_money(summary['used'])}，月度预算 {format_money(summary['quota'])}，剩余 {format_money(summary['remaining'])}，使用率 {summary['usage']:.1%}。",
    ]
    member_df = fetch_df(
        """
        SELECT u.display_name AS 员工,
               COALESCE(used.used_cost, 0) AS 已用费用,
               COALESCE(budget.monthly_quota, 0) AS 月度额度,
               CASE WHEN COALESCE(budget.monthly_quota, 0) > 0
                    THEN COALESCE(used.used_cost, 0) / budget.monthly_quota
                    ELSE 0 END AS 使用率
        FROM users u
        LEFT JOIN (
            SELECT user_id, SUM(cost_cny) AS used_cost
            FROM consumption_records
            WHERE department_id=? AND substr(record_date, 1, 7)=substr(?, 1, 7)
            GROUP BY user_id
        ) used ON used.user_id=u.id
        LEFT JOIN (
            SELECT user_id, SUM(monthly_quota) AS monthly_quota
            FROM user_budgets
            WHERE month=?
            GROUP BY user_id
        ) budget ON budget.user_id=u.id
        WHERE u.department_id=? AND u.role='employee' AND u.status='active'
        ORDER BY 使用率 DESC, 已用费用 DESC
        """,
        (user.department_id, month_start(), month_start(), user.department_id),
    )
    risky_members = member_df[member_df["使用率"] >= 1] if not member_df.empty else pd.DataFrame()
    if not risky_members.empty:
        row = risky_members.iloc[0]
        lines.append(f"预算超支最严重的员工是 **{row['员工']}**，已用 {format_money(row['已用费用'])}，额度 {format_money(row['月度额度'])}，使用率 {row['使用率']:.1%}。")
    elif not member_df.empty:
        row = member_df.iloc[0]
        lines.append(f"当前最需要关注的员工是 **{row['员工']}**，使用率 {row['使用率']:.1%}，已用 {format_money(row['已用费用'])}。")
    if not model_df.empty:
        row = model_df.iloc[0]
        lines.append(f"部门内费用最高模型是 **{row['模型']}**，本月费用 {format_money(row['费用'])}，建议复核该模型是否存在集中调用或低价值调用。")
    if summary["usage"] >= 0.8:
        lines.append("建议动作：优先审批真实业务需要的追加额度，同时要求高费用员工说明用途，并对高费用模型设置使用规范。")
    render_analysis_box("分析说明", lines, level)


def render_admin_analysis(dept_df: pd.DataFrame, model_rank_df: pd.DataFrame) -> None:
    total_used = float(dept_df["本月费用"].sum()) if not dept_df.empty else 0
    total_budget = float(dept_df["月度预算"].sum()) if not dept_df.empty else 0
    usage = total_used / total_budget if total_budget else 0
    status, level = usage_status(usage)
    lines = [
        f"全公司本月预算执行状态为 **{status}**：已用 {format_money(total_used)}，月度预算 {format_money(total_budget)}，整体使用率 {usage:.1%}。",
    ]
    if not dept_df.empty:
        over_depts = dept_df[dept_df["使用率"] >= 1].sort_values("使用率", ascending=False)
        focus_depts = over_depts if not over_depts.empty else dept_df.sort_values("使用率", ascending=False)
        row = focus_depts.iloc[0]
        lines.append(f"重点关注部门是 **{row['部门']}**，本月费用 {format_money(row['本月费用'])}，月度预算 {format_money(row['月度预算'])}，使用率 {row['使用率']:.1%}。")
    employee_df = fetch_df(
        """
        SELECT u.display_name AS 员工, d.name AS 部门,
               COALESCE(used.used_cost, 0) AS 已用费用,
               COALESCE(budget.monthly_quota, 0) AS 月度额度,
               CASE WHEN COALESCE(budget.monthly_quota, 0) > 0
                    THEN COALESCE(used.used_cost, 0) / budget.monthly_quota
                    ELSE 0 END AS 使用率
        FROM users u
        JOIN departments d ON d.id=u.department_id
        LEFT JOIN (
            SELECT user_id, SUM(cost_cny) AS used_cost
            FROM consumption_records
            WHERE substr(record_date, 1, 7)=substr(?, 1, 7)
            GROUP BY user_id
        ) used ON used.user_id=u.id
        LEFT JOIN (
            SELECT user_id, SUM(monthly_quota) AS monthly_quota
            FROM user_budgets
            WHERE month=?
            GROUP BY user_id
        ) budget ON budget.user_id=u.id
        WHERE u.role='employee' AND u.status='active'
        ORDER BY 使用率 DESC, 已用费用 DESC
        LIMIT 1
        """,
        (month_start(), month_start()),
    )
    if not employee_df.empty:
        row = employee_df.iloc[0]
        lines.append(f"重点关注员工是 **{row['员工']}**（{row['部门']}），已用 {format_money(row['已用费用'])}，额度 {format_money(row['月度额度'])}，使用率 {row['使用率']:.1%}。")
    if not model_rank_df.empty:
        row = model_rank_df.iloc[0]
        lines.append(f"费用最高模型是 **{row['模型']}**（{row['工具']}），本月费用 {format_money(row['费用'])}，应作为模型成本治理的第一优先级。")
    lines.append("建议动作：先处理超预算部门，再下钻到员工和模型；对高费用模型建立配额、审批和替代模型策略。")
    render_analysis_box("分析说明", lines, level)


def render_employee_dashboard(user: User) -> None:
    st.header("个人仪表盘")
    summary = get_user_month_summary(user.id, month_start())
    cols = st.columns(4)
    cols[0].metric("本月已用", format_money(summary["used"]))
    cols[1].metric("月度额度", format_money(summary["quota"]))
    cols[2].metric("剩余额度", format_money(summary["remaining"]))
    cols[3].metric("使用率", f"{summary['usage']:.1%}")
    if summary["usage"] >= 0.95:
        st.error("本月使用率已超过 95%，建议立即申请追加额度或控制使用。")
    elif summary["usage"] >= 0.8:
        st.warning("本月使用率已超过 80%，请关注后续使用。")

    quota_df = fetch_df(
        """
        SELECT t.name AS 工具,
               COALESCE(used.used_cost, 0) AS 已用费用,
               b.monthly_quota AS 月度额度,
               MAX(b.monthly_quota - COALESCE(used.used_cost, 0), 0) AS 剩余额度,
               CASE WHEN b.monthly_quota > 0 THEN COALESCE(used.used_cost, 0) / b.monthly_quota ELSE 0 END AS 使用率
        FROM user_budgets b
        JOIN tools t ON t.id=b.tool_id
        LEFT JOIN (
            SELECT tool_id, SUM(cost_cny) AS used_cost
            FROM consumption_records
            WHERE user_id=? AND substr(record_date, 1, 7)=substr(?, 1, 7)
            GROUP BY tool_id
        ) used ON used.tool_id=b.tool_id
        WHERE b.user_id=? AND b.month=?
        ORDER BY 使用率 DESC
        """,
        (user.id, month_start(), user.id, month_start()),
    )
    if not quota_df.empty:
        quota_display = quota_df.copy()
        quota_display["使用率"] = quota_display["使用率"].map(lambda value: f"{value:.1%}")
        st.subheader("本月各工具额度")
        st.dataframe(quota_display, hide_index=True, use_container_width=True)
        actual_df = quota_df[["工具", "已用费用", "月度额度"]].melt(
            id_vars="工具",
            value_vars=["已用费用", "月度额度"],
            var_name="类型",
            value_name="金额",
        )
        st.subheader("预实对比分析")
        st.plotly_chart(px.bar(actual_df, x="工具", y="金额", color="类型", barmode="group"), use_container_width=True)
    render_employee_analysis(user, summary, quota_df)

    tool_df = fetch_df(
        """
        SELECT t.name AS 工具, SUM(c.cost_cny) AS 费用
        FROM consumption_records c
        JOIN tools t ON t.id = c.tool_id
        WHERE c.user_id=? AND substr(c.record_date, 1, 7)=substr(?, 1, 7)
        GROUP BY t.name
        ORDER BY 费用 DESC
        """,
        (user.id, month_start()),
    )
    trend_df = fetch_df(
        """
        SELECT substr(record_date, 1, 7) AS 月份, SUM(cost_cny) AS 费用
        FROM consumption_records
        WHERE user_id=? AND record_date >= date('now', '-7 months')
        GROUP BY substr(record_date, 1, 7)
        ORDER BY 月份
        """,
        (user.id,),
    )
    left, right = st.columns(2)
    with left:
        st.subheader("工具费用分解")
        if tool_df.empty:
            st.info("暂无本月消费数据。")
        else:
            st.plotly_chart(px.bar(tool_df, x="费用", y="工具", orientation="h"), use_container_width=True)
    with right:
        st.subheader("近 6 个月趋势")
        if trend_df.empty:
            st.info("暂无趋势数据。")
        else:
            st.plotly_chart(px.line(trend_df, x="月份", y="费用", markers=True), use_container_width=True)


def render_consumption(user: User, department_id: int | None = None) -> None:
    title = "成员明细" if department_id else "消费明细"
    st.header(title)
    tools = fetch_df("SELECT id, name FROM tools WHERE status='active' ORDER BY name")
    with st.expander("筛选", expanded=True):
        col1, col2, col3 = st.columns(3)
        selected_tools = col1.multiselect("工具", tools["name"].tolist())
        start, end = col2.date_input(
            "日期范围",
            value=(date.today().replace(day=1) - timedelta(days=150), date.today()),
        )
        billing_label = col3.selectbox("计费类型", ["全部"] + list(BILLING_TYPE_LABELS.values()))
        billing = "全部"
        if billing_label != "全部":
            billing = {label: code for code, label in BILLING_TYPE_LABELS.items()}[billing_label]

    params: list[Any] = []
    where = []
    if department_id:
        where.append("c.department_id=?")
        params.append(department_id)
    else:
        where.append("c.user_id=?")
        params.append(user.id)
    where.append("date(c.record_date) BETWEEN date(?) AND date(?)")
    params.extend([start.isoformat(), end.isoformat()])
    if selected_tools:
        placeholders = ",".join("?" for _ in selected_tools)
        where.append(f"t.name IN ({placeholders})")
        params.extend(selected_tools)
    if billing != "全部":
        where.append("c.billing_type=?")
        params.append(billing)
    df = fetch_df(
        f"""
        SELECT c.record_date AS 日期, u.display_name AS 成员, t.name AS 工具, c.model_name AS 模型,
               c.tokens_input AS 输入token, c.tokens_output AS 输出token, c.api_calls AS API调用,
               c.cost_original AS 原币费用, c.currency AS 币种, c.cost_cny AS 人民币费用,
               c.billing_type AS 计费类型, c.source AS 来源
        FROM consumption_records c
        JOIN users u ON u.id = c.user_id
        JOIN tools t ON t.id = c.tool_id
        WHERE {' AND '.join(where)}
        ORDER BY c.record_date DESC, c.id DESC
        """,
        tuple(params),
    )
    if df.empty:
        st.info("当前筛选条件下暂无消费记录。")
        return
    st.dataframe(localize_df(df.head(PAGE_SIZE)), hide_index=True, use_container_width=True)
    st.caption(f"共 {len(df)} 条，当前展示前 {PAGE_SIZE} 条。")
    st.download_button("导出电子表格", to_excel(localize_df(df)), "消费明细.xlsx", use_container_width=False)


def render_quota_application(user: User) -> None:
    st.header("额度申请")
    tools = fetch_df("SELECT id, name FROM tools WHERE status='active' ORDER BY name")
    with st.form("quota_form"):
        col1, col2, col3 = st.columns(3)
        tool_name = col1.selectbox("申请工具", tools["name"].tolist())
        month_value = col2.date_input("生效月份", value=date.today().replace(day=1))
        amount = col3.number_input("申请金额", min_value=0.0, step=100.0)
        reason = st.text_area("申请理由", placeholder="请填写业务背景、预期使用场景和金额依据，至少 10 个字。")
        submitted = st.form_submit_button("提交申请")
    if submitted:
        tool_id = int(tools.loc[tools["name"] == tool_name, "id"].iloc[0])
        app_month = month_value.replace(day=1).isoformat()
        exists = fetch_one(
            """
            SELECT id FROM quota_applications
            WHERE user_id=? AND tool_id=? AND month=? AND status='pending'
            """,
            (user.id, tool_id, app_month),
        )
        if amount <= 0:
            st.error("申请金额必须大于 0。")
        elif len(reason.strip()) < 10:
            st.error("申请理由至少 10 个字。")
        elif exists:
            st.error("同月同工具已有待审批申请，请勿重复提交。")
        else:
            execute(
                """
                INSERT INTO quota_applications(user_id, department_id, tool_id, month, amount, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user.id, user.department_id, tool_id, app_month, amount, reason.strip(), local_now_text()),
            )
            add_audit(user.id, "create", "quota_application", tool_name, f"申请 {amount:.2f} 元")
            st.success("额度申请已提交，等待主管审批。")

    df = fetch_df(
        """
        SELECT q.created_at AS 提交时间, t.name AS 工具, q.month AS 月份, q.amount AS 申请金额,
               q.approved_amount AS 批准金额, q.status AS 状态, q.review_comment AS 审批意见
        FROM quota_applications q
        JOIN tools t ON t.id = q.tool_id
        WHERE q.user_id=?
        ORDER BY q.created_at DESC
        """,
        (user.id,),
    )
    st.subheader("申请记录")
    if df.empty:
        st.info("暂无额度申请记录。")
    else:
        st.dataframe(localize_df(df), hide_index=True, use_container_width=True)


def render_employee_alerts(user: User) -> None:
    st.header("预警通知")
    df = fetch_df(
        """
        SELECT id, created_at AS 时间, level AS 级别, title AS 标题, message AS 内容,
               CASE WHEN is_read=1 THEN '已读' ELSE '未读' END AS 状态
        FROM alerts
        WHERE user_id=? OR (scope='department' AND department_id=?)
        ORDER BY is_read, created_at DESC
        """,
        (user.id, user.department_id),
    )
    if df.empty:
        st.info("暂无预警通知。")
        return
    st.dataframe(localize_df(df.drop(columns=["id"])), hide_index=True, use_container_width=True)
    unread = df.loc[df["状态"] == "未读", "id"].tolist()
    if unread and st.button("全部标记为已读"):
        placeholders = ",".join("?" for _ in unread)
        execute(f"UPDATE alerts SET is_read=1 WHERE id IN ({placeholders})", tuple(unread))
        st.rerun()


def render_tool_rates() -> None:
    st.header("工具费率")
    df = fetch_df(
        """
        SELECT name AS 工具, billing_type AS 计费类型, currency AS 币种,
               unit_price AS 单价, monthly_seat_price AS 席位月租, status AS 状态
        FROM tools
        ORDER BY id
        """
    )
    st.dataframe(localize_df(df), hide_index=True, use_container_width=True)


def render_manager_dashboard(user: User) -> None:
    if not require_role(user, {"manager"}):
        return
    st.header("部门仪表盘")
    summary = get_department_month_summary(user.department_id or 0, month_start())
    cols = st.columns(4)
    cols[0].metric("本月部门已用", format_money(summary["used"]))
    cols[1].metric("月度预算", format_money(summary["quota"]))
    cols[2].metric("剩余额度", format_money(summary["remaining"]))
    cols[3].metric("使用率", f"{summary['usage']:.1%}")

    rank_df = fetch_df(
        """
        SELECT u.display_name AS 成员, SUM(c.cost_cny) AS 费用
        FROM consumption_records c
        JOIN users u ON u.id = c.user_id
        WHERE c.department_id=? AND substr(c.record_date, 1, 7)=substr(?, 1, 7)
        GROUP BY u.display_name
        ORDER BY 费用 DESC
        """,
        (user.department_id, month_start()),
    )
    model_df = fetch_df(
        """
        SELECT COALESCE(c.model_name, t.name) AS 模型, SUM(c.cost_cny) AS 费用
        FROM consumption_records c
        JOIN tools t ON t.id = c.tool_id
        WHERE c.department_id=? AND substr(c.record_date, 1, 7)=substr(?, 1, 7)
        GROUP BY COALESCE(c.model_name, t.name)
        ORDER BY 费用 DESC
        LIMIT 10
        """,
        (user.department_id, month_start()),
    )
    st.subheader("预实对比分析")
    dept_actual_df = pd.DataFrame(
        [
            {"指标": "月度预算", "金额": summary["quota"]},
            {"指标": "实际已用", "金额": summary["used"]},
            {"指标": "剩余额度", "金额": summary["remaining"]},
        ]
    )
    st.plotly_chart(px.bar(dept_actual_df, x="指标", y="金额", color="指标"), use_container_width=True)
    render_manager_analysis(user, summary, model_df)
    left, right = st.columns(2)
    with left:
        st.subheader("成员消费排行")
        if rank_df.empty:
            st.info("暂无部门消费数据。")
        else:
            st.plotly_chart(px.bar(rank_df, x="成员", y="费用"), use_container_width=True)
    with right:
        st.subheader("模型费用分布")
        if model_df.empty:
            st.info("暂无模型分布数据。")
        else:
            st.plotly_chart(px.pie(model_df, values="费用", names="模型", hole=0.45), use_container_width=True)


def render_quota_approval(user: User) -> None:
    if not require_role(user, {"manager"}):
        return
    st.header("额度审批")
    df = fetch_df(
        """
        SELECT q.id, q.created_at AS 提交时间, u.display_name AS 申请人, t.name AS 工具,
               q.month AS 月份, q.amount AS 申请金额, q.reason AS 理由, q.status AS 状态
        FROM quota_applications q
        JOIN users u ON u.id = q.user_id
        JOIN tools t ON t.id = q.tool_id
        WHERE q.department_id=? AND q.status='pending'
        ORDER BY q.created_at
        """,
        (user.department_id,),
    )
    st.subheader("待审批申请")
    if df.empty:
        st.info("暂无待审批申请。")
    else:
        st.dataframe(localize_df(df.drop(columns=["id"])), hide_index=True, use_container_width=True)
        selected_id = st.selectbox("选择申请单", df["id"].tolist(), format_func=lambda x: f"#{x} · {df.loc[df['id']==x, '申请人'].iloc[0]}")
        selected = df[df["id"] == selected_id].iloc[0]
        col1, col2 = st.columns(2)
        approved_amount = col1.number_input("批准金额", min_value=0.0, value=float(selected["申请金额"]), step=100.0)
        comment = col2.text_input("审批意见", value="同意追加额度")
        action_cols = st.columns(3)
        if action_cols[0].button("通过", type="primary"):
            review_application(selected_id, user, "approved", approved_amount, comment)
            st.success("审批通过并已追加额度。")
            st.rerun()
        if action_cols[1].button("部分通过"):
            review_application(selected_id, user, "partial", approved_amount, comment)
            st.success("已部分通过并追加批准额度。")
            st.rerun()
        if action_cols[2].button("驳回"):
            review_application(selected_id, user, "rejected", 0, comment or "驳回")
            st.warning("申请已驳回。")
            st.rerun()

    history_df = fetch_df(
        """
        SELECT q.reviewed_at AS 审批时间, q.created_at AS 提交时间, u.display_name AS 申请人,
               t.name AS 工具, q.month AS 月份, q.amount AS 申请金额,
               q.approved_amount AS 批准金额, q.status AS 状态, q.review_comment AS 审批意见
        FROM quota_applications q
        JOIN users u ON u.id = q.user_id
        JOIN tools t ON t.id = q.tool_id
        WHERE q.department_id=? AND q.status!='pending'
        ORDER BY q.reviewed_at DESC, q.created_at DESC
        LIMIT 100
        """,
        (user.department_id,),
    )
    st.subheader("审批记录")
    if history_df.empty:
        st.info("暂无审批记录。")
    else:
        st.dataframe(localize_df(history_df), hide_index=True, use_container_width=True)


def review_application(app_id: int, reviewer: User, status: str, approved_amount: float, comment: str) -> None:
    with get_conn() as conn:
        app = conn.execute("SELECT * FROM quota_applications WHERE id=? AND status='pending'", (app_id,)).fetchone()
        if not app:
            raise ValueError("申请不存在或已审批。")
        conn.execute(
            """
            UPDATE quota_applications
            SET status=?, approved_amount=?, reviewer_id=?, review_comment=?, reviewed_at=?
            WHERE id=?
            """,
            (status, approved_amount, reviewer.id, comment, local_now_text(), app_id),
        )
        if status in {"approved", "partial"} and approved_amount > 0:
            row = conn.execute(
                "SELECT id, monthly_quota FROM user_budgets WHERE user_id=? AND tool_id=? AND month=?",
                (app["user_id"], app["tool_id"], app["month"]),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE user_budgets SET monthly_quota=? WHERE id=?",
                    (row["monthly_quota"] + approved_amount, row["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO user_budgets(user_id, tool_id, month, monthly_quota) VALUES (?, ?, ?, ?)",
                    (app["user_id"], app["tool_id"], app["month"], approved_amount),
                )
            conn.execute(
                """
                INSERT INTO alerts(scope, user_id, department_id, level, title, message)
                VALUES ('employee', ?, ?, 'warning', '额度申请已审批', ?)
                """,
                (app["user_id"], app["department_id"], f"申请单 #{app_id} {STATUS_LABELS.get(status, status)}，批准金额 {approved_amount:.2f} 元。"),
            )
        conn.execute(
            "INSERT INTO audit_logs(actor_id, action, entity, entity_id, detail) VALUES (?, ?, 'quota_application', ?, ?)",
            (reviewer.id, status, str(app_id), comment),
        )


def render_department_budget(user: User) -> None:
    if not require_role(user, {"manager"}):
        return
    st.header("部门预算分配")
    members = fetch_df(
        "SELECT id, display_name FROM users WHERE department_id=? AND role='employee' AND status='active'",
        (user.department_id,),
    )
    tools = fetch_df("SELECT id, name FROM tools WHERE status='active' ORDER BY name")
    current = fetch_df(
        """
        SELECT u.display_name AS 成员, t.name AS 工具, b.month AS 月份, b.monthly_quota AS 月度额度
        FROM user_budgets b
        JOIN users u ON u.id = b.user_id
        LEFT JOIN tools t ON t.id = b.tool_id
        WHERE u.department_id=? AND b.month=?
        ORDER BY u.display_name, t.name
        """,
        (user.department_id, month_start()),
    )
    if not current.empty:
        st.dataframe(current, hide_index=True, use_container_width=True)
    with st.form("budget_allocate"):
        col1, col2, col3 = st.columns(3)
        member_name = col1.selectbox("成员", members["display_name"].tolist())
        tool_name = col2.selectbox("工具", tools["name"].tolist())
        quota = col3.number_input("月度额度", min_value=0.0, step=100.0, value=2500.0)
        submitted = st.form_submit_button("保存额度")
    if submitted:
        user_id = int(members.loc[members["display_name"] == member_name, "id"].iloc[0])
        tool_id = int(tools.loc[tools["name"] == tool_name, "id"].iloc[0])
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO user_budgets(user_id, tool_id, month, monthly_quota)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, tool_id, month) DO UPDATE SET monthly_quota=excluded.monthly_quota
                """,
                (user_id, tool_id, month_start(), quota),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor_id, action, entity, entity_id, detail) VALUES (?, 'upsert', 'user_budget', ?, ?)",
                (user.id, f"{user_id}-{tool_id}", f"设置 {member_name}/{tool_name} 月额度 {quota:.2f}"),
            )
        st.success("额度已保存。")


def render_company_overview(user: User) -> None:
    if not require_role(user, {"admin"}):
        return
    st.header("公司总览")
    month = month_start()
    cost = fetch_one(
        "SELECT COALESCE(SUM(cost_cny), 0) AS v FROM consumption_records WHERE substr(record_date, 1, 7)=substr(?, 1, 7)",
        (month,),
    )["v"]
    annual_budget = fetch_one(
        "SELECT COALESCE(SUM(annual_budget), 0) AS v FROM department_budgets WHERE year=?",
        (date.today().year,),
    )["v"]
    pending = fetch_one("SELECT COUNT(*) AS v FROM quota_applications WHERE status='pending'")["v"]
    users = fetch_one("SELECT COUNT(*) AS v FROM users WHERE status='active'")["v"]
    cols = st.columns(4)
    cols[0].metric("本月总费用", format_money(cost))
    cols[1].metric("年度预算", format_money(annual_budget))
    cols[2].metric("待审批申请", int(pending))
    cols[3].metric("活跃用户", int(users))

    dept_df = fetch_df(
        """
        SELECT d.name AS 部门,
               COALESCE(SUM(c.cost_cny), 0) AS 本月费用,
               COALESCE(b.annual_budget / 12.0, 0) AS 月度预算,
               CASE WHEN COALESCE(b.annual_budget, 0) > 0
                    THEN COALESCE(SUM(c.cost_cny), 0) / (b.annual_budget / 12.0)
                    ELSE 0 END AS 使用率
        FROM departments d
        LEFT JOIN consumption_records c ON c.department_id=d.id AND substr(c.record_date, 1, 7)=substr(?, 1, 7)
        LEFT JOIN department_budgets b ON b.department_id=d.id AND b.year=?
        GROUP BY d.name, b.annual_budget
        ORDER BY 使用率 DESC
        """,
        (month, date.today().year),
    )
    trend_df = fetch_df(
        """
        SELECT substr(record_date, 1, 7) AS 月份, SUM(cost_cny) AS 费用
        FROM consumption_records
        GROUP BY substr(record_date, 1, 7)
        ORDER BY 月份
        """,
    )
    model_rank_df = fetch_df(
        """
        SELECT COALESCE(c.model_name, t.name) AS 模型, t.name AS 工具, SUM(c.cost_cny) AS 费用
        FROM consumption_records c
        JOIN tools t ON t.id=c.tool_id
        WHERE substr(c.record_date, 1, 7)=substr(?, 1, 7)
        GROUP BY COALESCE(c.model_name, t.name), t.name
        ORDER BY 费用 DESC
        LIMIT 12
        """,
        (month,),
    )
    render_admin_analysis(dept_df, model_rank_df)
    left, right = st.columns(2)
    with left:
        st.subheader("各部门使用率")
        dept_chart = dept_df.copy()
        dept_chart["使用率百分比"] = dept_chart["使用率"] * 100
        st.plotly_chart(px.bar(dept_chart, x="部门", y="使用率百分比", hover_data=["本月费用", "月度预算"]), use_container_width=True)
    with right:
        st.subheader("公司费用趋势")
        st.plotly_chart(px.line(trend_df, x="月份", y="费用", markers=True), use_container_width=True)
    st.subheader("预实对比分析")
    company_actual_df = dept_df[["部门", "本月费用", "月度预算"]].melt(
        id_vars="部门",
        value_vars=["本月费用", "月度预算"],
        var_name="类型",
        value_name="金额",
    )
    st.plotly_chart(px.bar(company_actual_df, x="部门", y="金额", color="类型", barmode="group"), use_container_width=True)
    st.subheader("模型费用排行")
    if model_rank_df.empty:
        st.info("暂无模型费用数据。")
    else:
        st.plotly_chart(px.bar(model_rank_df, x="费用", y="模型", color="工具", orientation="h"), use_container_width=True)
    st.subheader("部门预算对比")
    dept_display = dept_df.copy()
    dept_display["使用率"] = dept_display["使用率"].map(lambda value: f"{value:.1%}")
    st.dataframe(localize_df(dept_display), hide_index=True, use_container_width=True)


def render_data_import(user: User) -> None:
    if not require_role(user, {"admin"}):
        return
    st.header("数据导入")
    st.caption("支持本地文件上传，也支持从大模型厂商或统一网关接口同步用量数据。")
    file_tab, api_tab = st.tabs(["文件上传", "厂商接口对接"])
    with file_tab:
        render_file_import(user)
    with api_tab:
        render_api_import(user)


def render_file_import(user: User) -> None:
    st.caption("支持 CSV/XLSX。请先下载模板，按模板填写后上传；模板列名用于系统识别，请勿修改。")
    st.download_button(
        "下载导入模板",
        data=get_import_template(),
        file_name="AI费用消费数据导入模板.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    uploaded = st.file_uploader("上传消费数据", type=["csv", "xlsx"])
    if uploaded is None:
        st.info("上传文件后会先展示校验结果，再写入数据库。")
        return
    try:
        if uploaded.name.endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)
    except Exception as exc:
        st.error(f"文件读取失败：{exc}")
        return
    ok, message, prepared = validate_import(df)
    if not ok:
        st.error(message)
        st.dataframe(localize_df(df.head(20)), hide_index=True, use_container_width=True)
        return
    st.success(message)
    st.dataframe(localize_df(prepared.head(20)), hide_index=True, use_container_width=True)
    if st.button("确认导入", type="primary"):
        batch_id = import_consumption(prepared, user.id)
        st.success(f"导入完成，批次号：{batch_id}")
        st.rerun()


def render_api_import(user: User) -> None:
    st.caption("适用于 OpenAI 兼容网关、DeepSeek、Claude、火山方舟或企业自建网关的用量接口。接口返回数据会先标准化为导入模板，再校验入库。")
    with st.expander("接口返回格式要求", expanded=False):
        st.markdown(
            """
            接口应返回 JSON。系统会自动识别 `data`、`records`、`items` 或 `usage` 数组字段。

            推荐字段：
            - 用户：`username` / `user` / `email`
            - 工具：`tool` / `provider` / `vendor`
            - 模型：`model_name` / `model`
            - 日期：`record_date` / `date` / `created_at`
            - 费用：`cost_cny` / `cost` / `amount`
            - 用量：`tokens_input`、`tokens_output`、`api_calls`
            """
        )
    vendor = st.selectbox("厂商/接口类型", ["OpenAI 兼容接口", "DeepSeek", "Claude", "火山方舟", "自定义接口"])
    default_base = {
        "OpenAI 兼容接口": "https://api.openai.com",
        "DeepSeek": "https://api.deepseek.com",
        "Claude": "https://api.anthropic.com",
        "火山方舟": "https://ark.cn-beijing.volces.com",
        "自定义接口": "",
    }[vendor]
    with st.form("api_import_form"):
        col1, col2 = st.columns(2)
        base_url = col1.text_input("接口根地址", value=default_base, placeholder="https://api.example.com")
        endpoint = col2.text_input("用量接口路径", value="/v1/usage", placeholder="/v1/usage")
        col3, col4, col5 = st.columns(3)
        start_date = col3.date_input("开始日期", value=date.today().replace(day=1))
        end_date = col4.date_input("结束日期", value=date.today())
        default_tool = col5.selectbox("默认工具映射", fetch_df("SELECT name FROM tools ORDER BY id")["name"].tolist())
        api_key = st.text_input("接口密钥", type="password", placeholder="Bearer Token，不会保存到数据库")
        submitted = st.form_submit_button("拉取并预览")
    if submitted:
        try:
            raw_payload = fetch_vendor_usage(base_url, endpoint, api_key, start_date, end_date)
            api_df = normalize_vendor_usage(raw_payload, default_tool)
        except Exception as exc:
            st.session_state.pop("api_import_prepared", None)
            st.error(f"接口拉取失败：{exc}")
            return
        if api_df.empty:
            st.session_state.pop("api_import_prepared", None)
            st.warning("接口返回成功，但没有可导入的用量记录。")
            return
        ok, message, prepared = validate_import(api_df)
        if not ok:
            st.session_state.pop("api_import_prepared", None)
            st.error(message)
            st.dataframe(localize_df(api_df.head(50)), hide_index=True, use_container_width=True)
            return
        st.session_state["api_import_prepared"] = prepared
        st.success(f"接口数据校验通过，共 {len(prepared)} 条。")
    prepared = st.session_state.get("api_import_prepared")
    if prepared is None:
        st.info("填写接口信息后点击“拉取并预览”。若厂商接口字段不同，可先由网关转换为上方推荐格式。")
        return
    st.dataframe(localize_df(prepared.head(50)), hide_index=True, use_container_width=True)
    if st.button("确认导入接口数据", type="primary"):
        batch_id = import_consumption(prepared, user.id, source="api")
        st.session_state.pop("api_import_prepared", None)
        st.success(f"接口数据导入完成，批次号：{batch_id}")
        st.rerun()


def validate_import(df: pd.DataFrame) -> tuple[bool, str, pd.DataFrame]:
    required = {"username", "tool", "record_date", "cost_cny"}
    missing = required - set(df.columns)
    if missing:
        return False, f"缺少必需列：{', '.join(sorted(missing))}", df
    prepared = df.copy()
    prepared["record_date"] = pd.to_datetime(prepared["record_date"], errors="coerce").dt.date
    prepared["cost_cny"] = pd.to_numeric(prepared["cost_cny"], errors="coerce")
    if prepared["record_date"].isna().any():
        return False, "record_date 存在无法识别的日期。", prepared
    if prepared["cost_cny"].isna().any() or (prepared["cost_cny"] < 0).any():
        return False, "cost_cny 必须为非负数字。", prepared
    users = set(fetch_df("SELECT username FROM users")["username"].tolist())
    tools = set(fetch_df("SELECT name FROM tools")["name"].tolist())
    bad_users = sorted(set(prepared["username"]) - users)
    bad_tools = sorted(set(prepared["tool"]) - tools)
    if bad_users:
        return False, f"未知用户：{', '.join(bad_users)}", prepared
    if bad_tools:
        return False, f"未知工具：{', '.join(bad_tools)}", prepared
    for col in ["model_name", "currency", "billing_type", "notes"]:
        if col not in prepared.columns:
            prepared[col] = ""
    for col in ["tokens_input", "tokens_output", "api_calls"]:
        if col not in prepared.columns:
            prepared[col] = 0
        prepared[col] = pd.to_numeric(prepared[col], errors="coerce").fillna(0).astype(int)
    prepared["currency"] = prepared["currency"].replace("", "CNY").fillna("CNY")
    return True, f"校验通过，共 {len(prepared)} 条记录。", prepared


def fetch_vendor_usage(base_url: str, endpoint: str, api_key: str, start_date: date, end_date: date) -> dict[str, Any]:
    if not base_url.strip() or not endpoint.strip():
        raise ValueError("接口根地址和用量接口路径不能为空。")
    if end_date < start_date:
        raise ValueError("结束日期不能早于开始日期。")
    base = base_url.rstrip("/")
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    query = urlencode({"start_date": start_date.isoformat(), "end_date": end_date.isoformat()})
    url = f"{base}{path}?{query}"
    headers = {"Accept": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    import json

    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("接口返回必须是 JSON 对象。")
    return payload


def normalize_vendor_usage(payload: dict[str, Any], default_tool: str) -> pd.DataFrame:
    records: Any = None
    for key in ("data", "records", "items", "usage"):
        if isinstance(payload.get(key), list):
            records = payload[key]
            break
    if records is None and isinstance(payload.get("data"), dict):
        for key in ("records", "items", "usage"):
            if isinstance(payload["data"].get(key), list):
                records = payload["data"][key]
                break
    if records is None:
        records = []
    rows: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        username = item.get("username") or item.get("user") or item.get("email")
        record_date = item.get("record_date") or item.get("date") or item.get("created_at") or date.today().isoformat()
        if isinstance(record_date, (int, float)):
            record_date = datetime.fromtimestamp(record_date, ZoneInfo(APP_TIMEZONE)).date().isoformat()
        cost = item.get("cost_cny", item.get("cost", item.get("amount", 0)))
        rows.append(
            {
                "username": username,
                "tool": item.get("tool") or item.get("provider") or item.get("vendor") or default_tool,
                "record_date": str(record_date)[:10],
                "cost_cny": cost,
                "model_name": item.get("model_name") or item.get("model") or "",
                "tokens_input": item.get("tokens_input") or item.get("input_tokens") or item.get("prompt_tokens") or 0,
                "tokens_output": item.get("tokens_output") or item.get("output_tokens") or item.get("completion_tokens") or 0,
                "api_calls": item.get("api_calls") or item.get("requests") or item.get("count") or 0,
                "currency": item.get("currency") or "CNY",
                "billing_type": item.get("billing_type") or "usage",
                "notes": item.get("notes") or "厂商接口同步",
            }
        )
    return pd.DataFrame(rows)


def import_consumption(df: pd.DataFrame, actor_id: int, source: str = "import") -> str:
    prefix = "api" if source == "api" else "imp"
    batch_id = f"{prefix}-{local_now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    with get_conn() as conn:
        users = {
            row["username"]: row
            for row in conn.execute("SELECT id, username, department_id FROM users").fetchall()
        }
        tools = {
            row["name"]: row
            for row in conn.execute("SELECT id, name, billing_type FROM tools").fetchall()
        }
        for _, row in df.iterrows():
            user = users[row["username"]]
            tool = tools[row["tool"]]
            billing_type = row["billing_type"] or tool["billing_type"]
            conn.execute(
                """
                INSERT INTO consumption_records(
                    user_id, department_id, tool_id, model_name, record_date, tokens_input,
                    tokens_output, api_calls, cost_original, currency, cost_cny, billing_type,
                    import_batch_id, source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    user["department_id"],
                    tool["id"],
                    row["model_name"],
                    row["record_date"].isoformat(),
                    int(row["tokens_input"]),
                    int(row["tokens_output"]),
                    int(row["api_calls"]),
                    float(row["cost_cny"]),
                    row["currency"],
                    float(row["cost_cny"]),
                    billing_type,
                    batch_id,
                    source,
                    row["notes"],
                ),
            )
        conn.execute(
            "INSERT INTO audit_logs(actor_id, action, entity, entity_id, detail) VALUES (?, 'import', 'consumption_records', ?, ?)",
            (actor_id, batch_id, f"{SOURCE_LABELS.get(source, source)} {len(df)} 条消费记录"),
        )
    generate_budget_alerts()
    return batch_id


def generate_budget_alerts() -> None:
    month = month_start()
    employees = fetch_df("SELECT id, department_id FROM users WHERE role='employee'")
    for _, employee in employees.iterrows():
        summary = get_user_month_summary(int(employee["id"]), month)
        level = "critical" if summary["usage"] >= 0.95 else "warning" if summary["usage"] >= 0.8 else ""
        if level:
            execute(
                """
                INSERT INTO alerts(scope, user_id, department_id, level, title, message)
                VALUES ('employee', ?, ?, ?, '预算使用预警', ?)
                """,
                (
                    int(employee["id"]),
                    int(employee["department_id"]),
                    level,
                    f"本月使用率 {summary['usage']:.1%}，已用 {summary['used']:.2f} 元。",
                ),
            )


def render_budget_admin(user: User) -> None:
    if not require_role(user, {"admin"}):
        return
    st.header("预算管理")
    departments = fetch_df("SELECT id, name FROM departments WHERE status='active' ORDER BY name")
    budgets = fetch_df(
        """
        SELECT d.name AS 部门, b.year AS 年份, b.annual_budget AS 年度预算
        FROM department_budgets b
        JOIN departments d ON d.id=b.department_id
        ORDER BY b.year DESC, d.name
        """
    )
    st.dataframe(localize_df(budgets), hide_index=True, use_container_width=True)
    with st.form("dept_budget"):
        col1, col2, col3 = st.columns(3)
        dept_name = col1.selectbox("部门", departments["name"].tolist())
        year = col2.number_input("年份", min_value=2024, max_value=2100, value=date.today().year)
        amount = col3.number_input("年度预算", min_value=0.0, step=10000.0)
        submitted = st.form_submit_button("保存")
    if submitted:
        dept_id = int(departments.loc[departments["name"] == dept_name, "id"].iloc[0])
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO department_budgets(department_id, year, annual_budget)
                VALUES (?, ?, ?)
                ON CONFLICT(department_id, year) DO UPDATE SET annual_budget=excluded.annual_budget
                """,
                (dept_id, int(year), amount),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor_id, action, entity, entity_id, detail) VALUES (?, 'upsert', 'department_budget', ?, ?)",
                (user.id, f"{dept_id}-{year}", f"{dept_name} {year} 年预算 {amount:.2f}"),
            )
        st.success("预算已保存。")
        st.rerun()


def render_user_admin(user: User) -> None:
    if not require_role(user, {"admin"}):
        return
    st.header("用户管理")
    df = fetch_df(
        """
        SELECT u.username AS 用户名, u.display_name AS 姓名, u.email AS 邮箱,
               d.name AS 部门, u.role AS 角色, u.status AS 状态
        FROM users u
        LEFT JOIN departments d ON d.id=u.department_id
        ORDER BY u.id
        """
    )
    st.dataframe(localize_df(df), hide_index=True, use_container_width=True)
    departments = fetch_df("SELECT id, name FROM departments WHERE status='active' ORDER BY name")
    with st.form("user_create"):
        st.subheader("新增用户")
        col1, col2, col3 = st.columns(3)
        username = col1.text_input("用户名")
        display_name = col2.text_input("姓名")
        role_label_selected = col3.selectbox("角色", list(ROLE_LABELS.values()))
        role = {label: code for code, label in ROLE_LABELS.items()}[role_label_selected]
        col4, col5 = st.columns(2)
        dept_name = col4.selectbox("部门", ["无"] + departments["name"].tolist())
        password = col5.text_input("初始密码", type="password", value="ChangeMe123")
        submitted = st.form_submit_button("创建用户")
    if submitted:
        if not username.strip() or not display_name.strip() or len(password) < 6:
            st.error("用户名、姓名必填，密码至少 6 位。")
            return
        dept_id = None if dept_name == "无" else int(departments.loc[departments["name"] == dept_name, "id"].iloc[0])
        try:
            execute(
                """
                INSERT INTO users(username, password_hash, display_name, department_id, role)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username.strip(), hash_password(password), display_name.strip(), dept_id, role),
            )
            add_audit(user.id, "create", "user", username.strip(), f"创建用户 {display_name.strip()}")
            st.success("用户已创建。")
            st.rerun()
        except sqlite3.IntegrityError:
            st.error("用户名已存在。")


def render_tool_admin(user: User) -> None:
    if not require_role(user, {"admin"}):
        return
    st.header("工具管理")
    df = fetch_df(
        "SELECT id, name AS 工具, billing_type AS 计费类型, currency AS 币种, unit_price AS 单价, monthly_seat_price AS 席位月租, status AS 状态 FROM tools ORDER BY id"
    )
    st.dataframe(localize_df(df.drop(columns=["id"])), hide_index=True, use_container_width=True)
    with st.form("tool_upsert"):
        col1, col2, col3 = st.columns(3)
        name = col1.text_input("工具名称")
        billing_label_selected = col2.selectbox("计费类型", list(BILLING_TYPE_LABELS.values()))
        billing_type = {label: code for code, label in BILLING_TYPE_LABELS.items()}[billing_label_selected]
        currency = col3.selectbox("币种", ["CNY", "USD"])
        col4, col5 = st.columns(2)
        unit_price = col4.number_input("单价", min_value=0.0, format="%.6f")
        monthly = col5.number_input("席位月租", min_value=0.0)
        submitted = st.form_submit_button("新增工具")
    if submitted:
        if not name.strip():
            st.error("工具名称不能为空。")
            return
        try:
            execute(
                "INSERT INTO tools(name, billing_type, currency, unit_price, monthly_seat_price) VALUES (?, ?, ?, ?, ?)",
                (name.strip(), billing_type, currency, unit_price, monthly),
            )
            add_audit(user.id, "create", "tool", name.strip(), "新增 AI 工具")
            st.success("工具已新增。")
            st.rerun()
        except sqlite3.IntegrityError:
            st.error("工具名称已存在。")


def render_alert_center(user: User) -> None:
    if not require_role(user, {"admin"}):
        return
    st.header("预警中心")
    if st.button("重新计算预算预警"):
        generate_budget_alerts()
        st.success("预警已重新计算。")
    df = fetch_df(
        """
        SELECT a.created_at AS 时间, a.scope AS 范围, COALESCE(u.display_name, '') AS 用户,
               COALESCE(d.name, '') AS 部门, a.level AS 级别, a.title AS 标题,
               a.message AS 内容, CASE WHEN a.is_read=1 THEN '已读' ELSE '未读' END AS 状态
        FROM alerts a
        LEFT JOIN users u ON u.id=a.user_id
        LEFT JOIN departments d ON d.id=a.department_id
        ORDER BY a.created_at DESC
        LIMIT 200
        """
    )
    if df.empty:
        st.info("暂无预警。")
    else:
        st.dataframe(localize_df(df), hide_index=True, use_container_width=True)


def render_audit_logs(user: User) -> None:
    if not require_role(user, {"admin"}):
        return
    st.header("审计日志")
    df = fetch_df(
        """
        SELECT l.created_at AS 时间, COALESCE(u.display_name, '系统') AS 操作人,
               l.action AS 动作, l.entity AS 对象, l.entity_id AS 对象ID, l.detail AS 详情
        FROM audit_logs l
        LEFT JOIN users u ON u.id=l.actor_id
        ORDER BY l.created_at DESC
        LIMIT 300
        """
    )
    if df.empty:
        st.info("暂无审计日志。")
    else:
        st.dataframe(localize_df(df), hide_index=True, use_container_width=True)


def render_department_report(user: User) -> None:
    if not require_role(user, {"manager"}):
        return
    st.header("部门报表")
    df = fetch_df(
        """
        SELECT substr(c.record_date, 1, 7) AS 月份, u.display_name AS 成员, t.name AS 工具,
               SUM(c.cost_cny) AS 费用, SUM(c.tokens_input) AS 输入token,
               SUM(c.tokens_output) AS 输出token, SUM(c.api_calls) AS API调用
        FROM consumption_records c
        JOIN users u ON u.id=c.user_id
        JOIN tools t ON t.id=c.tool_id
        WHERE c.department_id=?
        GROUP BY substr(c.record_date, 1, 7), u.display_name, t.name
        ORDER BY 月份 DESC, 费用 DESC
        """,
        (user.department_id,),
    )
    if df.empty:
        st.info("暂无可导出的部门报表。")
        return
    st.dataframe(localize_df(df), hide_index=True, use_container_width=True)
    st.download_button("导出部门月报", to_excel(localize_df(df)), "部门费用月报.xlsx")


def render_page(user: User, page: str) -> None:
    if page == "个人仪表盘":
        render_employee_dashboard(user)
    elif page == "消费明细":
        render_consumption(user)
    elif page == "额度申请":
        render_quota_application(user)
    elif page == "预警通知":
        render_employee_alerts(user)
    elif page == "工具费率":
        render_tool_rates()
    elif page == "部门仪表盘":
        render_manager_dashboard(user)
    elif page == "成员明细":
        render_consumption(user, user.department_id)
    elif page == "额度审批":
        render_quota_approval(user)
    elif page == "部门预算分配":
        render_department_budget(user)
    elif page == "部门报表":
        render_department_report(user)
    elif page == "公司总览":
        render_company_overview(user)
    elif page == "数据导入":
        render_data_import(user)
    elif page == "预算管理":
        render_budget_admin(user)
    elif page == "用户管理":
        render_user_admin(user)
    elif page == "工具管理":
        render_tool_admin(user)
    elif page == "预警中心":
        render_alert_center(user)
    elif page == "审计日志":
        render_audit_logs(user)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="💰", layout="wide")
    inject_css()
    init_db()
    ensure_demo_data()
    user = get_current_user()
    if not user:
        render_login()
        return
    page = render_sidebar(user)
    render_page(user, page)


if __name__ == "__main__":
    main()
