
import logging 
from modules.check_admin_utils import check_admin


logging.basicConfig(
    level=logging.INFO, # 可以暂时设置为 DEBUG 级别以获取更多信息
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def handle_help_command(event, client, account_config, account_name):
    """显示所有命令及用途"""
    logger.info(f"Received /help command from {event.sender_id}")
    if not event.is_private or not await check_admin(event, account_config):
        return
    help_text = (
        "可用命令列表：\n"
        "/help - 显示本帮助信息\n"
        "/watch_text <源chatid> <目标chatid> <关键词> - 文字监控转发（*为全部）\n"
        "/watch_media <源chatid> <目标chatid> [type] - 媒体监控转发，type 可选：all, photo, video, image, document, audio, text，all 表示所有文件，默认仅常见媒体\n"
        "/batch_forward <源chatid> <目标chatid> <数量> [跳过数量] - 批量转发历史图片和视频\n"
        "/status - 查看当前账号状态和监控规则\n"
        "/config - 查看和设置配置项（例如：/config show, /config set auto_download true）\n"
    )
    await event.respond(help_text, parse_mode='markdown')


async def safe_send_message(target_id, text, client):
    """安全发送消息，自动兼容 int/用户名两种写法，并捕获实体找不到等异常"""
    try:
        # 尝试将 target_id 转为 int，如果是纯数字
        if isinstance(target_id, str) and target_id.lstrip('-').isdigit():
            target_id = int(target_id)
        await client.send_message(target_id, text)
    except ValueError as e:
        logger.error(f"无法找到目标实体 {target_id}，请确保机器人已与目标建立对话或在群组/频道内。错误: {e}")
    except Exception as e:
        logger.error(f"发送消息到 {target_id} 时出错: {e}")


async def handle_msginfo_command(event, client, account_config, account_name):
    """处理 /msginfo 命令，显示被回复消息的详细信息，支持群组/频道/私聊"""
    logger.info(f"Received /msginfo command from {event.sender_id}")
    # 只允许管理员使用，无论私聊还是群组/频道
    if not await check_admin(event, account_config):
        return
    try:
        # 必须是回复消息
        if not event.is_reply:
            await event.respond("请在回复一条消息的情况下使用 /msginfo。")
            return
        reply_msg = await event.get_reply_message()
        if not reply_msg:
            await event.respond("未能获取被回复的消息。")
            return
        info = (
            f"**消息详细信息：**\n"
            f"chat_id: `{reply_msg.chat_id}`\n"
            f"message_id: `{reply_msg.id}`\n"
            f"from_id: `{getattr(reply_msg, 'from_id', None)}`\n"
            f"sender_username: `{getattr(reply_msg.sender, 'username', None)}`\n"
            f"chat_title: `{getattr(reply_msg.chat, 'title', None)}`\n"
            f"内容: `{(reply_msg.text or getattr(reply_msg, 'message', None) or getattr(reply_msg, 'raw_text', None) or '')[:100]}`"
        )
        await event.respond(info, parse_mode='markdown')
    except Exception as e:
        logger.error(f"Error in handle_msginfo_command: {e}", exc_info=True)
        await event.respond(f"获取消息信息失败: {e}")