# AI 费用管理平台 Streamlit 应用

这是根据 `AI费用管理平台_Streamlit设计文档.md` 实现的可部署 Streamlit 原型，覆盖三类角色视图、费用明细、预算、额度申请审批、数据导入、预警和审计日志。

## 运行

```powershell
pip install -r requirements.txt
streamlit run app.py
```

首次启动会自动创建 SQLite 数据库：`data/ai_cost.db`。

## 演示账号

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `admin123` |
| 部门主管 | `manager` | `manager123` |
| 员工 | `employee` | `employee123` |

运行 `python seed_demo_data.py` 后，会额外创建覆盖 5 个部门的主管和员工演示账号，密码统一为 `demo123`。例如：`tech_mgr`、`prod_mgr`、`tech_alice`、`mkt_jack`。

## 演示造数

```powershell
python seed_demo_data.py
python verify_demo_data.py
```

造数脚本会清理并重建批次 `demo-100-v1`，插入 100 条消费记录，覆盖 8 个工具、20 个模型、5 个部门，并生成额度申请、审批结果和超预算预警。

## 导入格式

支持 CSV/XLSX。必需列：

- `username`
- `tool`
- `record_date`
- `cost_cny`

可选列：

- `model_name`
- `tokens_input`
- `tokens_output`
- `api_calls`
- `currency`
- `billing_type`
- `notes`
