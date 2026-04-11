"""配置管理模块"""
import os
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# 加载 .env 文件
env_path = Path('.env')
if env_path.exists():
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# ==================== Bot 配置 ====================
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]

# 工作群组 ID（指挥官 bot 和其他 bot 所在的群组）
WORK_GROUP_ID = int(os.environ.get('WORK_GROUP_ID', '0'))

# ==================== LLM 配置 ====================
LLM_API_URL = os.environ.get('LLM_API_URL', '').rstrip('/')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
LLM_MAX_TOKENS = int(os.environ.get('LLM_MAX_TOKENS', '512'))
LLM_TEMPERATURE = float(os.environ.get('LLM_TEMPERATURE', '0.3'))

# ==================== 安全配置 ====================
# 频率限制：每个 bot 每秒最多发送的消息数
RATE_LIMIT_PER_BOT = float(os.environ.get('RATE_LIMIT_PER_BOT', '1.0'))
# 最大交互深度（防止循环）
MAX_INTERACTION_DEPTH = int(os.environ.get('MAX_INTERACTION_DEPTH', '5'))
# 超时时间（秒）
RESPONSE_TIMEOUT = int(os.environ.get('RESPONSE_TIMEOUT', '30'))
# 消息去重窗口（秒）
DEDUP_WINDOW = int(os.environ.get('DEDUP_WINDOW', '60'))

# ==================== 加载技能描述 ====================
SKILLS_PATH = Path(__file__).parent / 'skills.yml'


def load_skills() -> dict:
    """加载 skills.yml 技能描述文件"""
    if not SKILLS_PATH.exists():
        logger.warning("skills.yml 文件不存在")
        return {}
    with SKILLS_PATH.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('bots', {})


def get_enabled_bots() -> dict:
    """获取所有已启用的 bot"""
    skills = load_skills()
    return {k: v for k, v in skills.items() if v.get('enabled', False)}


def build_skills_prompt() -> str:
    """构建给 LLM 的技能描述 prompt"""
    skills = load_skills()
    if not skills:
        return "当前没有配置任何技能 bot。"

    lines = ["你可以调用以下 bot 来完成用户的请求：\n"]
    for key, info in skills.items():
        status = "✅ 已启用" if info.get('enabled') else "❌ 已禁用"
        lines.append(f"### {info.get('name', key)} (@{info.get('username', 'unknown')}) [{status}]")
        lines.append(f"描述: {info.get('description', '').strip()}")
        if info.get('how_to_use'):
            lines.append(f"使用方式: {info.get('how_to_use', '').strip()}")
        if info.get('input_type'):
            lines.append(f"输入类型: {info.get('input_type')}")
        if info.get('admin_only'):
            lines.append("注意: 此 bot 仅管理员可用")
        lines.append("")
    return "\n".join(lines)


logger.info(
    "Config loaded. ADMIN_IDS: %s, WORK_GROUP_ID: %s, LLM_MODEL: %s",
    ADMIN_IDS, WORK_GROUP_ID, LLM_MODEL
)