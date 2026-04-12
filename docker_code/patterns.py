"""
消息提取 & 类型识别模块

新增 bot 类型只需在 TYPE_RULES 表中加一行，无需改逻辑。
"""
import re
from typing import Callable

# ── 提取消息的正则表达式 ──────────────────────────────────
PATTERN = re.compile(
    r'(?:'
    r'@(?:FilesPan1Bot|MediaBK5Bot|FilesDrive_BLGA_bot)\s+[^\s]+.*'
    r'|showfilesbot_\d+[PpvVdD]_[A-Za-z0-9_\-\+]+'
    r'|(?:vi|pk|[dvp])_(?:FilesPan1Bot_)?[A-Za-z0-9_\-\+]+'
    r'|[A-Za-z0-9_\-\+]+=[^=\s]*?(?:_grp|_mda)(?=[\s\u4e00-\u9fa5]|$)'
    r'|@filepan_bot:([A-Za-z0-9_\-\+]+)'
    r'|mtfxq2?bot_[A-Za-z0-9_\-\+]+'
    r')',
    re.IGNORECASE,
)


def extract_messages(text: str) -> list[str]:
    """从文本中提取匹配的消息列表"""
    matches = []
    for m in PATTERN.finditer(text):
        match = m.group(0)
        if match.endswith("_grp") or match.endswith("_mda"):
            end_pos = match.find("_grp")
            if end_pos == -1:
                end_pos = match.find("_mda")
            if end_pos != -1:
                match = match[: end_pos + 4]
        matches.append(match)
    return matches


# ── Bot 类型识别（方案 A：纯正则规则表）───────────────────
#
# 每条规则：(正则, 类型标签)
#   - 标签为 str  → 直接使用
#   - 标签为 Callable → 传入 re.Match，返回类型字符串
#
# 规则按优先级从上到下匹配，命中即返回。
# 新增 bot 类型只需在末尾（或合适位置）加一行。

TYPE_RULES: list[tuple[str, str | Callable]] = [
    # --- 包含 @bot 标识的（优先级最高）---
    (r"@FilesDrive_BLGA_bot", "filesdrive"),
    (r"@FilesPan1Bot", "filespan1"),
    (r"@MediaBK5Bot", "mediabk5"),
    (r"@filepan_bot:", "filepan_bot"),

    # --- showfilesbot 前缀 ---
    (r"^showfilesbot_", "showfilesbot-code"),

    # --- 老版本格式 vi_ / pk_ ---
    (r"^(vi|pk)_", lambda m: m.group(1) + "_old"),

    # --- 新版本格式 d_/v_/p_ + 含 FilesPan1Bot ---
    (r"^([dvp])_.*FilesPan1Bot_", lambda m: "filespan1bot_" + m.group(1)),

    # --- 新版本格式 d_/v_/p_（不含 FilesPan1Bot）---
    (r"^([dvp])_", lambda m: m.group(1) + "_new"),

    # --- mtfxq2bot / mtfxqbot ---
    (r"^mtfxq2bot_", "mtfxq2bot"),
    (r"^mtfxqbot_", "mtfxqbot"),

    # --- _grp / _mda 后缀 → mediabk5bot ---
    (r"(_grp|_mda)$", "mediabk5bot"),
]

# 预编译正则
_COMPILED_RULES: list[tuple[re.Pattern, str | Callable]] = [
    (re.compile(p, re.IGNORECASE), label) for p, label in TYPE_RULES
]

# 用于多 bot 检测的关键字集合
_BOT_KEYWORDS = {"@FilesDrive_BLGA_bot", "@FilesPan1Bot", "@MediaBK5Bot", "@filepan_bot:"}


def _has_multiple_bots(message: str) -> bool:
    """检查消息中是否包含多个 bot 标识"""
    return sum(1 for kw in _BOT_KEYWORDS if kw in message) > 1


def classify_message(message: str) -> str | None:
    """
    根据规则表识别消息所属的 bot 类型。
    返回类型标签，无法识别时返回 None。
    """
    if _has_multiple_bots(message):
        return None

    for pattern, label in _COMPILED_RULES:
        m = pattern.search(message)
        if m:
            return label(m) if callable(label) else label

    return None