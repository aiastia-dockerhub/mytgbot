"""LLM API 客户端 - 兼容 OpenAI 格式"""
import logging
from typing import Optional

import httpx

from config import LLM_API_URL, LLM_API_KEY, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE

logger = logging.getLogger(__name__)


async def chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Optional[str]:
    """
    调用 OpenAI 兼容的 Chat Completion API

    Args:
        messages: 消息列表 [{"role": "system/user/assistant", "content": "..."}]
        model: 模型名称（默认使用配置值）
        max_tokens: 最大 token 数
        temperature: 温度参数

    Returns:
        LLM 回复的文本内容，失败返回 None
    """
    model = model or LLM_MODEL
    max_tokens = max_tokens or LLM_MAX_TOKENS
    temperature = temperature if temperature is not None else LLM_TEMPERATURE

    if not LLM_API_URL:
        logger.error("LLM_API_URL 未配置")
        return None

    # 构建请求 URL（支持用户传入完整的 URL 或只有 base URL）
    url = LLM_API_URL
    if not url.endswith('/chat/completions'):
        url = f"{url}/chat/completions"

    headers = {
        "Content-Type": "application/json",
    }
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            logger.info("LLM 回复: %s", content[:200])
            return content
    except httpx.HTTPStatusError as e:
        logger.error("LLM API HTTP 错误: %s, 响应: %s", e, e.response.text[:500])
        return None
    except Exception as e:
        logger.error("LLM API 调用失败: %s", e)
        return None


async def analyze_intent(user_message: str, skills_prompt: str) -> Optional[dict]:
    """
    分析用户消息的意图，返回路由信息

    Returns:
        {
            "action": "route_to_bot" | "chat_reply" | "unknown",
            "bot_key": "sticker2img" | ... (当 action=route_to_bot 时),
            "bot_username": "@xxx_bot",
            "command": "要发送给目标 bot 的内容",
            "reason": "判断理由"
        }
    """
    system_prompt = f"""你是一个 Telegram Bot 指挥官的意图分析模块。
你的任务是分析用户消息，判断应该路由到哪个 bot 处理。

{skills_prompt}

请根据用户消息判断意图，返回 JSON 格式（不要包含其他内容）：
- 如果用户的请求匹配某个已启用的 bot，返回：
  {{"action": "route_to_bot", "bot_key": "bot的key", "bot_username": "bot的username（不带@）", "command": "要发送的内容或命令", "reason": "判断理由"}}
- 如果是普通聊天/问答，返回：
  {{"action": "chat_reply", "reply": "你的回复内容", "reason": "这是普通对话"}}
- 如果无法判断，返回：
  {{"action": "unknown", "reason": "无法判断意图"}}

注意：
1. 只路由到 enabled 的 bot
2. 如果用户发送的是贴纸/表情包相关请求，路由到 sticker2img
3. command 字段应该是发送给目标 bot 的实际内容
4. 返回纯 JSON，不要 markdown 代码块"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    response = await chat_completion(messages, temperature=0.1)
    if not response:
        return {"action": "unknown", "reason": "LLM 调用失败"}

    # 清理响应（移除可能的 markdown 代码块标记）
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        import json
        result = json.loads(response)
        logger.info("意图分析结果: %s", result)
        return result
    except Exception as e:
        logger.error("解析 LLM 响应失败: %s, 原始响应: %s", e, response)
        return {"action": "unknown", "reason": f"解析失败: {response[:200]}"}