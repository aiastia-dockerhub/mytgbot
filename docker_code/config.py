"""配置管理模块"""
import os
from pathlib import Path


def load_env() -> None:
    """从 .env 文件加载环境变量"""
    env_path = Path(".env")
    if env_path.exists():
        print("从 .env 文件加载配置...")
        with env_path.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value


load_env()

# ── 配置项 ────────────────────────────────────────────────

BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x) for x in os.environ.get("ADMIN_IDS", "12345678").split(",")
    if x.strip().isdigit()
]
DB_PATH: str = os.environ.get("DB_PATH", "data/messages.db")

print(f"管理员ID列表: {ADMIN_IDS}")