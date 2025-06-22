
import logging
import re   
from modules.check_admin_utils import check_admin
from modules.handle_watch_text import persist_rules

logging.basicConfig(
    level=logging.INFO, # 可以暂时设置为 DEBUG 级别以获取更多信息
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)



async def handle_watch_media_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules):
    """命令格式: /watch_media 源chatid 目标chatid [type]"""
    logger.info(f"Received /watch_media command from {event.sender_id}: {event.text}")
    if not event.is_private or not await check_admin(event, account_config):
        return
    try:
        args = event.text.strip().split()
        if len(args) < 3:
            await event.respond("用法: /watch_media <源chatid> <目标chatid> [type] (type 可选: all, photo, video, image, document, audio, text)")
            return
        # 只允许 - 和数字，去除其它字符
        source_id = re.sub(r'[^-\d]', '', args[1].strip())
        target_id = re.sub(r'[^-\d]', '', args[2].strip())
        media_type = args[3].lower() if len(args) > 3 else None
        # 存储为 dict，支持类型
        media_watch_rules[source_id] = {'target_id': target_id, 'type': media_type}
        persist_rules(account_name, text_watch_rules, media_watch_rules)
        await event.respond(f"已添加媒体监控: 源: `{source_id}` -> 目标: `{target_id}` 类型: `{media_type or 'media'}`", parse_mode='markdown')
    except Exception as e:
        logger.error(f"Error handling /watch_media command: {e}", exc_info=True)
        await event.respond(f"添加失败: {e}")

async def handle_unwatch_media_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules):
    """命令格式: /unwatch_media 源chatid"""
    logger.info(f"Received /unwatch_media command from {event.sender_id}: {event.text}")
    if not event.is_private or not await check_admin(event, account_config):
        return
    try:
        args = event.text.strip().split()
        if len(args) != 2:
            await event.respond("用法: /unwatch_media <源chatid>")
            return
        source_id = str(args[1].strip())  # 只 strip 空格
        if source_id in media_watch_rules:
            del media_watch_rules[source_id]
            persist_rules(account_name, text_watch_rules, media_watch_rules)
            await event.respond(f"已删除媒体监控: 源: `{source_id}`", parse_mode='markdown')
        else:
            await event.respond(f"未找到对应的媒体监控规则。", parse_mode='markdown')
    except Exception as e:
        logger.error(f"Error handling /unwatch_media command: {e}", exc_info=True)
        await event.respond(f"删除失败: {e}")
