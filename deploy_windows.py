import os
import sys
import subprocess
import venv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQ_FILE = PROJECT_ROOT / "requirements.txt"


def create_venv() -> None:
    if VENV_DIR.exists():
        print(f"虚拟环境已存在：{VENV_DIR}")
        return
    print("正在创建虚拟环境 .venv …")
    venv.EnvBuilder(with_pip=True).create(str(VENV_DIR))
    print("虚拟环境创建完成。")


def pip_install(requirements: Path) -> None:
    if not requirements.exists():
        print("未找到 requirements.txt，跳过依赖安装。")
        return
    python_exe = VENV_DIR / "Scripts" / "python.exe"
    if not python_exe.exists():
        print("未找到虚拟环境 Python，请先创建 .venv。")
        sys.exit(1)
    print("开始安装依赖 …")
    subprocess.check_call([str(python_exe), "-m", "pip", "install", "-U", "pip"])
    subprocess.check_call([str(python_exe), "-m", "pip", "install", "-r", str(requirements)])
    print("依赖安装完成。")


def write_env_example() -> None:
    example = (
        "SMTP_HOST=smtp.example.com\n"
        "SMTP_PORT=465\n"
        "SMTP_USER=your_account@example.com\n"
        "SMTP_PASS=your_app_password\n\n"
        "OPENAI_API_KEY=sk-xxxxxx\n"
    )
    (PROJECT_ROOT / ".env.example").write_text(example, encoding="utf-8")
    print("已生成 .env.example，请复制为 .env 并填入实际值。")


def main():
    create_env = "--create-env" in sys.argv
    create_venv()
    pip_install(REQ_FILE)
    if create_env:
        write_env_example()
    print("部署完成。你可以执行：")
    print(f"  {VENV_DIR}\\Scripts\\Activate")
    print("  python workflow_1010.py")


if __name__ == "__main__":
    main()


