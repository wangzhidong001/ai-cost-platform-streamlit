# 锐捷AI费用管理系统 Streamlit 应用

这是根据 `AI费用管理平台_Streamlit设计文档.md` 实现的可部署 Streamlit 原型，覆盖三类角色视图、费用明细、预算、额度申请审批、数据导入、预警和审计日志。

## 运行

```powershell
pip install -r requirements.txt
streamlit run app.py
```

首次启动会自动创建 SQLite 数据库：`data/ai_cost.db`。

## 7×24 在线部署

临时公网隧道适合演示，不适合长期在线。需要同事随时登录时，建议部署到公司内网服务器或云服务器：

```bash
docker compose up -d --build
```

服务地址：

```text
http://172.27.135.214:8501
```

部署到其他服务器时，将 `172.27.135.214` 替换为对应服务器内网 IP。

容器已配置自动重启和健康检查，数据库保存在 Docker 卷 `ai-cost-data` 中。

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

## 大模型厂商接口对接

管理员在“数据导入 → 厂商接口对接”中填写接口根地址、用量接口路径、密钥和日期范围。系统会以 Bearer Token 调用接口，并识别 `data`、`records`、`items` 或 `usage` 数组。

推荐接口返回字段：

- `username`：平台用户名
- `tool`：平台中的工具名称
- `record_date`：消费日期
- `cost_cny`：人民币费用
- `model_name`：模型名称
- `tokens_input` / `tokens_output` / `api_calls`

接口密钥只在当前请求中使用，不写入数据库。
