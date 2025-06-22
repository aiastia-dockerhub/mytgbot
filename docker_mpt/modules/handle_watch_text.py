import logging
import yaml
from modules.check_admin_utils import check_admin


logging.basicConfig(
    level=logging.INFO, # 可以暂时设置为 DEBUG 级别以获取更多信息
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def handle_watch_text_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules):
    """命令格式: /watch_text 源chatid 目标chatid 关键词"""
    logger.info(f"Received /watch_text command from {event.sender_id}: {event.text}")
    if not event.is_private or not await check_admin(event, account_config):
        return
    try:
        args = event.text.strip().split()
        if len(args) != 4:
            await event.respond("用法: /watch_text <源chatid> <目标chatid> <关键词>")
            return
        source_id = str(args[1].strip())  # 只 strip 空格
        target_id = str(args[2].strip())
        keyword = args[3]
        text_watch_rules[(source_id, keyword)] = target_id
        persist_rules(account_name, text_watch_rules, media_watch_rules)
        await event.respond(f"已添加文字监控: 源: `{source_id}` -> 目标: `{target_id}`，关键词: `{keyword}`", parse_mode='markdown')
    except Exception as e:
        logger.error(f"Error handling /watch_text command: {e}", exc_info=True)
        await event.respond(f"添加失败: {e}")

def persist_rules(account_name, text_watch_rules, media_watch_rules):
    config_path = 'config.yaml'
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            full_config = yaml.safe_load(f)
        found = False
        for acc in full_config['accounts']:
            if acc['name'] == account_name:
                acc['text_watch_rules'] = [
                    {'source_id': sid, 'keyword': keyword, 'target_id': tid}
                    for (sid, keyword), tid in text_watch_rules.items()
                ]
                acc['media_watch_rules'] = [
                    {'source_id': sid, 'target_id': v['target_id'], 'type': v['type']} if isinstance(v, dict) else {'source_id': sid, 'target_id': v, 'type': None}
                    for sid, v in media_watch_rules.items()
                ]
                found = True
                break
        if not found:
            logger.warning(f"Could not find account '{account_name}' in config.yaml to persist rules.")
            return
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(full_config, f, allow_unicode=True, indent=2)
        logger.info(f"Rules for account {account_name} persisted to config.yaml.")
    except Exception as e:
        logger.error(f"Error persisting rules for account {account_name}: {e}")



async def handle_unwatch_text_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules):
    """命令格式: /unwatch_text 源chatid 关键词"""
    logger.info(f"Received /unwatch_text command from {event.sender_id}: {event.text}")
    if not event.is_private or not await check_admin(event, account_config):
        return
    try:
        args = event.text.strip().split()
        if len(args) != 3:
            await event.respond("用法: /unwatch_text <源chatid> <关键词>")
            return
        source_id = str(args[1].strip())  # 只 strip 空格
        keyword = args[2]
        key = (source_id, keyword)
        if key in text_watch_rules:
            del text_watch_rules[key]
            persist_rules(account_name, text_watch_rules, media_watch_rules)
            await event.respond(f"已删除文字监控: 源: `{source_id}` 关键词: `{keyword}`", parse_mode='markdown')
        else:
            await event.respond(f"未找到对应的文字监控规则。", parse_mode='markdown')
    except Exception as e:
        logger.error(f"Error handling /unwatch_text command: {e}", exc_info=True)
        await event.respond(f"删除失败: {e}")
