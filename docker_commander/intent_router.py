"""意图识别与路由模块"""
import logging
from typing import Optional

from config import load_skills, get_enabled_bots, build_skills_prompt
from llm_client import analyze_intent

logger = logging.getLogger(__name__)


class IntentRouter:
    """意图路由器 - 判断用户消息应该交给哪个 bot 处理"""

    def __init__(self):
        self._skills_prompt = None

    @property
    def skills_prompt(self) -> str:
        """懒加载技能描述 prompt"""
        if self._skills_prompt is None:
            self._skills_prompt = build_skills_prompt()
        return self._skills_prompt

    def reload_skills(self):
        """重新加载技能描述"""
        self._skills_prompt = None
        logger.info("技能描述已重新加载")

    async def route(self, user_message: str, input_type: str = "text") -> dict:
        """
        路由用户消息

        Args:
            user_message: 用户的消息文本
            input_type: 输入类型 (text/sticker/media)

        Returns:
            路由结果 dict:
            - action: "route_to_bot" | "chat_reply" | "unknown"
            - bot_key: 目标 bot 的 key (可选)
            - bot_username: 目标 bot 的 username (可选)
            - command: 发送给目标 bot 的内容 (可选)
            - reply: 聊天回复内容 (可选)
            - reason: 判断理由
        """
        # 对于贴纸类型，直接路由到 sticker2img（不经过 LLM）
        if input_type == "sticker":
            return self._route_sticker()

        # 对于文本消息，使用 LLM 分析意图
        return await self._route_text(user_message)

    def _route_sticker(self) -> dict:
        """贴纸直接路由到 sticker2img"""
        enabled = get_enabled_bots()
        if "sticker2img" in enabled:
            info = enabled["sticker2img"]
            return {
                "action": "route_to_bot",
                "bot_key": "sticker2img",
                "bot_username": info.get("username", ""),
                "command": "forward_sticker",
                "reason": "用户发送了贴纸，直接路由到贴纸转图片 bot",
            }
        return {
            "action": "unknown",
            "reason": "收到贴纸，但 sticker2img bot 未启用",
        }

    async def _route_text(self, user_message: str) -> dict:
        """文本消息通过 LLM 分析意图"""
        result = await analyze_intent(user_message, self.skills_prompt)

        if result is None:
            return {"action": "unknown", "reason": "LLM 返回空结果"}

        # 验证 route_to_bot 的目标是否确实已启用
        if result.get("action") == "route_to_bot":
            bot_key = result.get("bot_key", "")
            enabled = get_enabled_bots()
            if bot_key not in enabled:
                logger.warning(
                    "LLM 路由到了未启用的 bot: %s，降级为 chat_reply", bot_key
                )
                return {
                    "action": "chat_reply",
                    "reply": f"抱歉，{bot_key} bot 当前未启用。已通知管理员。",
                    "reason": f"目标 bot {bot_key} 未启用",
                }
            # 确保 username 正确
            result["bot_username"] = enabled[bot_key].get("username", result.get("bot_username", ""))

        return result