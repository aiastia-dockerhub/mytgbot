"""Bot 管理器 - 负责 Bot-to-Bot 通信、防循环、频率限制"""
import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    WORK_GROUP_ID,
    RATE_LIMIT_PER_BOT,
    MAX_INTERACTION_DEPTH,
    RESPONSE_TIMEOUT,
    DEDUP_WINDOW,
    get_enabled_bots,
)

logger = logging.getLogger(__name__)


class BotManager:
    """管理 Bot-to-Bot 通信"""

    def __init__(self):
        # 频率限制：记录每个 bot 最后发送时间
        self._last_send_time: dict[str, float] = {}
        # 消息去重：记录已处理的 message_id
        self._processed_messages: dict[int, float] = {}
        # 交互深度计数
        self._interaction_depth: dict[str, int] = defaultdict(int)
        # 等待响应的任务 {bot_username: (event, key)}
        self._pending_responses: dict[int, tuple[asyncio.Event, str]] = {}
        # 缓存的工作群消息 ID（用于收集响应）
        self._response_cache: dict[int, str] = {}
        # 缓存的完整 message 对象（用于转发媒体）
        self._response_message_cache: dict[int, object] = {}
        # 超时后的兜底转发：记录 bot_username → (user_chat_id, expire_time)
        self._late_forward_map: dict[str, tuple[int, float]] = {}
        # bot 对象引用（用于兜底转发）
        self._bot = None

    def _check_rate_limit(self, bot_username: str) -> bool:
        """检查频率限制"""
        now = time.time()
        last = self._last_send_time.get(bot_username, 0)
        if now - last < (1.0 / RATE_LIMIT_PER_BOT):
            return False  # 被限流
        self._last_send_time[bot_username] = now
        return True

    def _is_duplicate(self, message_id: int) -> bool:
        """检查消息是否重复"""
        now = time.time()
        # 清理过期的去重记录
        expired = [mid for mid, t in self._processed_messages.items() if now - t > DEDUP_WINDOW]
        for mid in expired:
            del self._processed_messages[mid]

        if message_id in self._processed_messages:
            return True
        self._processed_messages[message_id] = now
        return False

    def _check_depth(self, bot_username: str) -> bool:
        """检查交互深度"""
        return self._interaction_depth[bot_username] < MAX_INTERACTION_DEPTH

    def _increment_depth(self, bot_username: str):
        """增加交互深度"""
        self._interaction_depth[bot_username] += 1

    def _decrement_depth(self, bot_username: str):
        """减少交互深度"""
        if self._interaction_depth[bot_username] > 0:
            self._interaction_depth[bot_username] -= 1

    async def send_to_bot(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        bot_username: str,
        command: str,
        sticker_file_id: Optional[str] = None,
    ) -> Optional[int]:
        """
        在工作群中向目标 bot 发送消息

        Args:
            context: Bot context
            bot_username: 目标 bot 的 username（不带@）
            command: 要发送的命令或文本
            sticker_file_id: 贴纸 file_id（如果是转发贴纸）

        Returns:
            发送的消息 ID，失败返回 None
        """
        if not self._check_rate_limit(bot_username):
            logger.warning("频率限制: 向 @%s 发送被限流", bot_username)
            return None

        if not self._check_depth(bot_username):
            logger.warning("交互深度超限: @%s", bot_username)
            return None

        if not WORK_GROUP_ID:
            logger.error("WORK_GROUP_ID 未配置")
            return None

        self._increment_depth(bot_username)

        try:
            if sticker_file_id:
                # 转发贴纸到工作群
                msg = await context.bot.send_sticker(
                    chat_id=WORK_GROUP_ID,
                    sticker=sticker_file_id,
                )
                # 发送 @提及回复贴纸，确保子 bot 在隐私模式下也能感知
                # bot 收到 @mention 后可通过 reply_to_message 获取贴纸
                await context.bot.send_message(
                    chat_id=WORK_GROUP_ID,
                    text=f"@{bot_username}",
                    reply_to_message_id=msg.message_id,
                )
            else:
                # 发送命令到工作群，使用 @bot_username 格式
                # 如果 command 已经是 /command 格式，追加 @bot_username
                text = command
                if text.startswith("/"):
                    # 在命令后追加 @bot_username
                    parts = text.split(" ", 1)
                    cmd = parts[0]
                    args = parts[1] if len(parts) > 1 else ""
                    text = f"{cmd}@{bot_username}"
                    if args:
                        text += f" {args}"
                else:
                    # 非命令文本，直接 @bot_username
                    text = f"@{bot_username} {text}"

                msg = await context.bot.send_message(
                    chat_id=WORK_GROUP_ID,
                    text=text,
                )

            logger.info("已发送消息到 @%s (msg_id: %d)", bot_username, msg.message_id)
            return msg.message_id

        except Exception as e:
            logger.error("发送消息到 @%s 失败: %s", bot_username, e)
            self._decrement_depth(bot_username)
            return None

    async def wait_for_response(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        bot_username: str,
        timeout: Optional[int] = None,
    ) -> Optional[str]:
        """
        等待目标 bot 在工作群中的回复

        Args:
            context: Bot context
            bot_username: 目标 bot 的 username
            timeout: 超时秒数

        Returns:
            目标 bot 的回复文本，超时返回 None
        """
        timeout = timeout or RESPONSE_TIMEOUT

        # 创建等待事件
        event = asyncio.Event()
        key = f"{bot_username}_{time.time()}"
        self._pending_responses[bot_username] = (event, key)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            # 等一小段时间，让 bot 发送的所有回复消息都被收集
            # （例如 sticker2img 会发送多条消息：photo + document）
            await asyncio.sleep(2)
            # 获取缓存的响应文本
            response = self._response_cache.pop(bot_username, None)
            msgs = self._response_message_cache.get(bot_username, [])
            logger.info(
                "wait_for_response 返回: bot=%s, response=%s, 收集到 %d 条消息",
                bot_username, repr(response[:100]) if response else None, len(msgs),
            )
            return response
        except asyncio.TimeoutError:
            logger.warning("等待 @%s 回复超时 (%ds)", bot_username, timeout)
            # 超时后清理
            self._response_message_cache.pop(bot_username, None)
            return None
        finally:
            self._pending_responses.pop(bot_username, None)
            self._decrement_depth(bot_username)

    def pop_response_message(self, bot_username: str):
        """获取并清除缓存的响应消息对象列表（用于转发媒体）"""
        msgs = self._response_message_cache.pop(bot_username, None)
        logger.info("pop_response_message: bot=%s, msgs=%s", bot_username, type(msgs).__name__ if msgs else None)
        if msgs:
            logger.info("  消息数量: %d", len(msgs) if isinstance(msgs, list) else 1)
        return msgs

    async def handle_bot_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理工作群中来自其他 bot 的回复消息

        当工作群中收到来自 bot 的消息时调用此方法
        """
        message = update.message
        if not message:
            return

        # 消息去重
        if self._is_duplicate(message.message_id):
            return

        # 检查是否来自 bot
        from_user = message.from_user
        if not from_user or not from_user.is_bot:
            return

        bot_username = from_user.username or ""
        response_text = message.text or message.caption or "[媒体/文件]"

        # 收集响应类型信息，用于转发媒体消息
        response_type = "text"
        if message.photo:
            response_type = "photo"
        elif message.document:
            response_type = "document"
        elif message.video:
            response_type = "video"
        elif message.animation:
            response_type = "animation"
        elif message.sticker:
            response_type = "sticker"

        logger.info(
            "收到来自 @%s 的回复 (类型: %s): %s",
            bot_username, response_type, response_text[:200],
        )

        # 如果有等待此 bot 响应的任务，收集所有响应
        logger.info(
            "检查等待列表: bot_username=%s, pending_bots=%s",
            bot_username, list(self._pending_responses.keys()),
        )
        if bot_username in self._pending_responses:
            self._response_cache[bot_username] = response_text
            # 存储完整的 message 对象列表，用于转发所有媒体
            if bot_username not in self._response_message_cache:
                self._response_message_cache[bot_username] = []
            self._response_message_cache[bot_username].append(message)
            event, _ = self._pending_responses[bot_username]
            event.set()
        elif bot_username in self._late_forward_map:
            # 超时后的兜底转发：直接发送给用户
            chat_id, expire = self._late_forward_map[bot_username]
            if time.time() < expire:
                logger.info("兜底转发: @%s 的回复转发给用户 chat_id=%d", bot_username, chat_id)
                await self._forward_late_response(message, chat_id, bot_username)
            else:
                self._late_forward_map.pop(bot_username, None)

        return response_text

    def reset_depth(self, bot_username: str = None):
        """重置交互深度"""
        if bot_username:
            self._interaction_depth[bot_username] = 0
        else:
            self._interaction_depth.clear()

    def set_bot(self, bot):
        """设置 bot 对象引用（用于兜底转发）"""
        self._bot = bot

    def register_late_forward(self, bot_username: str, chat_id: int, ttl: int = 300):
        """注册兜底转发：超时后如果 bot 仍然回复，直接转发给用户"""
        self._late_forward_map[bot_username] = (chat_id, time.time() + ttl)
        logger.info("已注册兜底转发: @%s → chat_id=%d (TTL=%ds)", bot_username, chat_id, ttl)

    async def _forward_late_response(self, message, chat_id: int, bot_username: str):
        """兜底转发：将超时后到达的回复直接发送给用户"""
        try:
            if message.photo:
                photo = message.photo[-1]
                await self._bot.send_photo(
                    chat_id=chat_id,
                    photo=photo.file_id,
                    caption=f"✅ @{bot_username} (延迟回复)",
                )
            elif message.document:
                await self._bot.send_document(
                    chat_id=chat_id,
                    document=message.document.file_id,
                    caption=message.caption or f"✅ @{bot_username} (延迟回复)",
                )
            elif message.video:
                await self._bot.send_video(
                    chat_id=chat_id,
                    video=message.video.file_id,
                    caption=message.caption or f"✅ @{bot_username} (延迟回复)",
                )
            elif message.animation:
                await self._bot.send_animation(
                    chat_id=chat_id,
                    animation=message.animation.file_id,
                    caption=f"✅ @{bot_username} (延迟回复)",
                )
            elif message.sticker:
                await self._bot.send_sticker(
                    chat_id=chat_id,
                    sticker=message.sticker.file_id,
                )
            elif message.text:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ @{bot_username} (延迟回复):\n\n{message.text[:4000]}",
                )
        except Exception as e:
            logger.error("兜底转发失败: %s", e)

    def get_status(self) -> dict:
        """获取所有 bot 的状态"""
        enabled = get_enabled_bots()
        status = {}
        for key, info in enabled.items():
            username = info.get("username", "unknown")
            status[key] = {
                "name": info.get("name", key),
                "username": f"@{username}",
                "interaction_depth": self._interaction_depth.get(username, 0),
                "pending": username in self._pending_responses,
            }
        return status