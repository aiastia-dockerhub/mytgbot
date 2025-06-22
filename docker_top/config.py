import os
import ast
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

def parse_env_set(val, default=None):
    try:
        return ast.literal_eval(val)
    except Exception:
        return default
TOKEN = os.getenv('TOKEN', '').strip('"')
API_BASE = os.getenv('API_BASE', '').strip('"')
HIDE_CATEGORY_IDS = parse_env_set(os.getenv('HIDE_CATEGORY_IDS', 'set()'), set())
HIDE_LINK_IDS = parse_env_set(os.getenv('HIDE_LINK_IDS', 'set()'), set())
HIDE_LINK_KEYWORDS = parse_env_set(os.getenv('HIDE_LINK_KEYWORDS', '[]'), [])
