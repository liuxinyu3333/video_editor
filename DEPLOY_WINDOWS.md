### 部署说明（Windows / PowerShell）

以下步骤将帮助你在新电脑上部署并运行 `workflow_1010.py`。

---

### 1) 安装必备软件
- 安装 Python 3.11（或 ≥3.9）
- 可选：安装 Git（若使用 Git 克隆仓库）

---

### 2) 获取项目代码
将项目放到 `E:\coin_works\project`（或任意路径）。若使用 Git：
```powershell
git clone <你的仓库地址> E:\coin_works\project
```

---

### 3) 打开 PowerShell 并进入项目目录
```powershell
cd E:\coin_works\project
```

---

### 4) 一键部署脚本（推荐）
执行：
```powershell
python deploy_windows.py --create-env
```
脚本会：
- 创建虚拟环境 `.venv`
- 安装 `requirements.txt`
- 可选生成 `.env.example`（包含邮箱与 OpenAI Key 的示例变量）

随后你可以将 `.env.example` 复制为 `.env` 并填入实际值：
```powershell
copy .env.example .env
```

---

### 5) 手动部署（可选）
如果不使用脚本，可手动执行：
```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -U pip
pip install -r requirements.txt
```

---

### 6) 配置环境变量（建议用 .env 文件）
项目内可能用到的配置（示例）：
```
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USER=your_account@example.com
SMTP_PASS=your_app_password

OPENAI_API_KEY=sk-xxxxxx
```
如果你的代码未读取 `.env`，请在相关模块（如 `Email_sender.py`、`ask_gpt_api1009.py`）中改为通过 `os.getenv` 读取。

---

### 7) 运行主流程
```powershell
.\.venv\Scripts\Activate
python workflow_1010.py
```

---

### 8) 常见问题
- ImportError：某些包未安装 → 运行 `pip install -r requirements.txt` 或单独安装
- 邮件发送失败 → 检查 SMTP 相关变量、端口（465/587）及应用专用密码
- OpenAI/代理问题 → 确认 `OPENAI_API_KEY` 与网络连通性（如需代理，自己在代码或系统配置）


