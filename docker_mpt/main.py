import os
import yaml
import logging
from telethon import TelegramClient, events
from db.base import init_db
from db.models import Account
from db.base import SessionLocal
import asyncio
from telethon.errors import SessionPasswordNeededError
from modules.offset_utils import handle_offset_for_id_command, is_media_type
from modules.check_admin_utils import check_admin
from modules.handle_watch_text import handle_watch_text_command, handle_unwatch_text_command
from modules.handle_watch_media import handle_watch_media_command, handle_unwatch_media_command
from modules.handle_help import handle_help_command, handle_msginfo_command
from modules.handle_mes import handle_message
from modules.handle_batch import handle_batch_forward_command, handle_batch_forward_command_v2
# Configure logging
logging.basicConfig(
    level=logging.INFO, # 可以暂时设置为 DEBUG 级别以获取更多信息
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load configuration
try:
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    logger.info("config.yaml loaded successfully.")
    # 打印部分关键配置，确认是否加载正确
    logger.info(f"API ID: {config.get('api_id')}")
    logger.info(f"API Hash: {'*' * (len(config.get('api_hash', '')) - 4) + config.get('api_hash', '')[-4:]}") # 只显示后四位
    # IMPORTANT: Ensure admin_ids is a list in config.yaml, e.g., admin_ids: [123456789]
    logger.info(f"Admin IDs: {config.get('admin_ids')}") 
except FileNotFoundError:
    logger.critical("config.yaml not found! Please create it based on the example.")
    exit(1)
except Exception as e:
    logger.critical(f"Error loading config.yaml: {e}")
    exit(1)

# Initialize database
try:
    init_db()
    logger.info("Database initialized successfully.")
except Exception as e:
    logger.critical(f"Error initializing database: {e}")
    exit(1)

# =====================
# 下面是无类的纯函数式实现
# =====================

def load_persisted_rules(account_config):
    text_watch_rules = {}
    media_watch_rules = {}
    text_rules = account_config.get('text_watch_rules', [])
    for rule in text_rules:
        text_watch_rules[(str(rule['source_id']), rule['keyword'])] = str(rule['target_id'])
    media_rules = account_config.get('media_watch_rules', [])
    for rule in media_rules:
        if isinstance(rule, dict):
            media_watch_rules[str(rule['source_id'])] = {'target_id': str(rule['target_id']), 'type': rule.get('type')}
        else:
            media_watch_rules[str(rule['source_id'])] = {'target_id': str(rule), 'type': None}
    return text_watch_rules, media_watch_rules


def persist_config_changes_to_file(account_name, account_config, text_watch_rules, media_watch_rules):
    config_path = 'config.yaml'
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            full_config = yaml.safe_load(f)
        found = False
        for i, acc in enumerate(full_config['accounts']):
            if acc['name'] == account_name:
                full_config['accounts'][i]['monitoring'] = account_config.get('monitoring', {})
                full_config['accounts'][i]['storage'] = account_config.get('storage', {})
                full_config['accounts'][i]['text_watch_rules'] = [
                    {'source_id': sid, 'keyword': keyword, 'target_id': tid}
                    for (sid, keyword), tid in text_watch_rules.items()
                ]
                full_config['accounts'][i]['media_watch_rules'] = [
                    {'source_id': sid, 'target_id': v['target_id'], 'type': v.get('type')}
                    if isinstance(v, dict) else {'source_id': sid, 'target_id': v, 'type': None}
                    for sid, v in media_watch_rules.items()
                ]
                found = True
                break
        if not found:
            logger.warning(f"Could not find account '{account_name}' in full_config to persist general config changes.")
            return
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(full_config, f, allow_unicode=True, indent=2)
        logger.info(f"General config changes for account {account_name} persisted to config.yaml.")
    except Exception as e:
        logger.error(f"Error persisting general config changes for account {account_name}: {e}")

def get_db_account(account_name, session_name):
    db = SessionLocal()
    try:
        db_account = db.query(Account).filter(
            Account.name == account_name,
            Account.session_name == session_name
        ).first()
        if not db_account:
            db_account = Account(
                name=account_name,
                session_name=session_name,
                is_active=True
            )
            db.add(db_account)
            db.commit()
            db.refresh(db_account)
        else:
            if not db_account.is_active:
                db_account.is_active = True
                db.commit()
                db.refresh(db_account)
        logger.info(f"Database account initialized: {db_account.id}, Name: {db_account.name}, Session: {db_account.session_name}")
        return db_account
    except Exception as e:
        logger.error(f"Error initializing database account: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def setup_handlers(client, account_config, account_name, db_account, text_watch_rules, media_watch_rules):
    logger.info(f"Setting up event handlers for account {account_name}...")
    
    # 使用 lambda 函数包装 async 方法，确保它们能在内部类中被正确引用
    @client.on(events.NewMessage)
    async def _handle_new_message(event):
        await handle_message(event, client, account_config, account_name, db_account, text_watch_rules, media_watch_rules)
    
    @client.on(events.NewMessage(pattern='/watch_text'))
    async def _handle_watch_text_command(event):
        await handle_watch_text_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules)
    
    @client.on(events.NewMessage(pattern='/watch_media'))
    async def _handle_watch_media_command(event):
        await handle_watch_media_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules)
    
    @client.on(events.NewMessage(pattern='/batch_forward'))
    async def _handle_batch_forward_command(event):
        await handle_batch_forward_command(event, client, account_config, account_name, db_account, text_watch_rules, media_watch_rules)
    @client.on(events.NewMessage(pattern='/batch_forward_v2'))
    async def _handle_batch_forward_v2(event):
        await handle_batch_forward_command_v2(event, client, account_config, account_name, db_account, text_watch_rules, media_watch_rules)

    @client.on(events.NewMessage(pattern='/help'))
    async def _handle_help_command(event):
        await handle_help_command(event, client, account_config, account_name)
    
    @client.on(events.NewMessage(pattern='/status'))
    async def _handle_account_command(event):
        await handle_account_command(event, client, account_config, account_name, db_account, text_watch_rules, media_watch_rules)
    
    @client.on(events.NewMessage(pattern='/config'))
    async def _handle_config_command(event):
        await handle_config_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules)
    
    @client.on(events.NewMessage(pattern='/msginfo'))
    async def _handle_msginfo_command(event):
        await handle_msginfo_command(event, client, account_config, account_name)
    
    @client.on(events.NewMessage(pattern='/unwatch_text'))
    async def _handle_unwatch_text_command(event):
        await handle_unwatch_text_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules)

    @client.on(events.NewMessage(pattern='/unwatch_media'))
    async def _handle_unwatch_media_command(event):
        await handle_unwatch_media_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules)
    
    @client.on(events.NewMessage(pattern='/offset_for_id'))
    async def _handle_offset_for_id_command(event):
        await handle_offset_for_id_command(event, client, account_config, account_name)
    
    logger.info(f"Event handlers for account {account_name} are now active.")



async def handle_account_command(event, client, account_config, account_name, db_account, text_watch_rules, media_watch_rules):
    """Handle account status command"""
    logger.info(f"Received /status command from {event.sender_id}")
    if not event.is_private or not await check_admin(event, account_config):
        return
    
    try:
        response = f"*Account Status for {account_name}:*\n\n"
        response += f"Name: `{account_name}`\n"
        response += f"Session: `{account_config['session_name']}`\n"
        response += f"Status: `{'Active' if db_account.is_active else 'Inactive'}`\n"
        response += f"Created: `{db_account.created_at.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        response += f"\n*当前监控规则:*\n"
        if not text_watch_rules and not media_watch_rules:
            response += "暂无监控规则。\n"
        else:
            for (sid, keyword), tid in text_watch_rules.items():
                response += f"文字: 源:`{sid}` -> 目标:`{tid}` | 关键词: `{keyword}`\n"
            for sid, tid in media_watch_rules.items():
                response += f"媒体: 源:`{sid}` -> 目标:`{tid}`\n"
        await event.respond(response, parse_mode='markdown')
            
    except Exception as e:
        logger.error(f"Error handling account command: {e}", exc_info=True)
        await event.respond(f"处理状态命令时出错: {e}")

async def handle_config_command(event, client, account_config, account_name, text_watch_rules, media_watch_rules):
    """处理配置命令"""
    logger.info(f"Received /config command from {event.sender_id}: {event.text}")
    if not event.is_private or not await check_admin(event, account_config):
        return

    try:
        args = event.text.split()[1:] # 去掉命令本身
        if not args:
            await event.respond(
                "用法:\n"
                "`/config show` - 显示当前配置\n"
                "`/config set <选项> <值>` - 设置配置选项\n"
                "可用选项:\n"
                "- `auto_forward_media`: 是否自动转发媒体文件 (true/false)\n"
                "- `monitor_private_bots`: 是否监控机器人私聊 (true/false)\n"
                "- `auto_download`: 是否自动下载媒体文件 (true/false)\n"
                "- `enabled_chats`: 设置监控的群组/频道ID (例如: `/config set enabled_chats -100123456789 -100987654321`)"
                "- `bot_usernames`: 设置监控的机器人用户名 (例如: `/config set bot_usernames MyBotUsername AnotherBot`)"
                , parse_mode='markdown'
            )
            return

        action = args[0].lower()
        if action == "show":
            response = "*当前配置:*\n"
            response += f"自动转发媒体文件 (auto_forward_media): `{account_config['monitoring'].get('auto_forward_media', False)}`\n"
            response += f"监控机器人私聊 (monitor_private_bots): `{account_config['monitoring'].get('monitor_private_bots', False)}`\n"
            response += f"自动下载媒体文件 (auto_download): `{account_config['storage'].get('auto_download', False)}`\n"
            response += f"监控的群组/频道 (enabled_chats): `{', '.join(map(str, account_config['monitoring'].get('enabled_chats', []))) or '所有'}`\n"
            response += f"监控的机器人用户名 (bot_usernames): `{', '.join(account_config['monitoring'].get('bot_usernames', [])) or '所有机器人'}`"
            await event.respond(response, parse_mode='markdown')

        elif action == "set":
            if len(args) < 3: # 至少需要 set, option, value
                await event.respond("用法: `/config set <选项> <值>`", parse_mode='markdown')
                return

            option = args[1].lower()
            value_args = args[2:]

            if option in ['auto_forward_media', 'monitor_private_bots', 'auto_download']:
                if len(value_args) != 1 or value_args[0].lower() not in ['true', 'false']:
                    await event.respond(f"值必须是 `true` 或 `false`。", parse_mode='markdown')
                    return
                value = value_args[0].lower() == 'true'
                if option == 'auto_forward_media':
                    account_config['monitoring']['auto_forward_media'] = value
                    await event.respond(f"已{'启用' if value else '禁用'}自动转发媒体文件。")
                elif option == 'monitor_private_bots':
                    account_config['monitoring']['monitor_private_bots'] = value
                    await event.respond(f"已{'启用' if value else '禁用'}监控机器人私聊。")
                elif option == 'auto_download':
                    account_config['storage']['auto_download'] = value
                    await event.respond(f"已{'启用' if value else '禁用'}自动下载媒体文件。")
                persist_config_changes_to_file(account_name, account_config, text_watch_rules, media_watch_rules) # 保存到文件
                
            elif option == 'enabled_chats':
                # 允许设置多个chatid，将它们转换为整数列表
                try:
                    chat_ids = [int(cid) for cid in value_args]
                    account_config['monitoring']['enabled_chats'] = chat_ids
                    persist_config_changes_to_file(account_name, account_config, text_watch_rules, media_watch_rules)
                    await event.respond(f"已设置监控的群组/频道ID: `{', '.join(map(str, chat_ids))}`", parse_mode='markdown')
                except ValueError:
                    await event.respond("`enabled_chats` 的值必须是有效的数字ID列表。", parse_mode='markdown')
                    
            elif option == 'bot_usernames':
                # 允许设置多个机器人用户名
                account_config['monitoring']['bot_usernames'] = value_args # 直接使用列表
                persist_config_changes_to_file(account_name, account_config, text_watch_rules, media_watch_rules)
                await event.respond(f"已设置监控的机器人用户名: `{', '.join(value_args) or '无'}`", parse_mode='markdown')

            else:
                await event.respond("未知选项。", parse_mode='markdown')

        else:
            await event.respond("未知命令动作。请使用 `show` 或 `set`。", parse_mode='markdown')

    except Exception as e:
        logger.error(f"处理配置命令时出错: {str(e)}", exc_info=True)
        await event.respond(f"处理命令时出错: {str(e)}")

async def main():
    logger.info("Starting main bot loop...")
    clients = []
    for account_config in config['accounts']:
        if account_config.get('enabled', False):
            account_name = account_config['name']
            logger.info(f"Initializing account: {account_name}")
            text_watch_rules, media_watch_rules = load_persisted_rules(account_config)
            custom_api = account_config.get('custom_api')
            proxy = None
            if custom_api and custom_api.get('enable', False):
                proxy_type = custom_api.get('proxy_type', 'socks5')
                host = custom_api.get('host')
                port = int(custom_api.get('port'))
                username = custom_api.get('username')
                password = custom_api.get('password')
                if proxy_type == 'mtproxy':
                    secret = custom_api.get('secret')
                    proxy = (proxy_type, host, port, secret)
                elif username and password:
                    proxy = (proxy_type, host, port, username, password)
                else:
                    proxy = (proxy_type, host, port)
                logger.info(f"Using proxy: {proxy_type}://{host}:{port}")
            client_kwargs = {
                "session": account_config['session_name'],
                "api_id": config['api_id'],
                "api_hash": config['api_hash'],
                "connection_retries": 10,
                "retry_delay": 2,
                "timeout": 60,
                "auto_reconnect": True
            }
            if proxy:
                client_kwargs["proxy"] = proxy
            client = TelegramClient(**client_kwargs)
            await client.connect()
            if not await client.is_user_authorized():
                phone = input(f"Enter phone number for account {account_name}: ")
                await client.send_code_request(phone)
                code = input(f"Enter the code you received for account {account_name}: ")
                try:
                    await client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    password = input(f"Enter 2FA password for account {account_name}: ")
                    await client.sign_in(password=password)
                logger.info(f"Account {account_name} logged in successfully")
            else:
                logger.info(f"Account {account_name} is already authorized.")
            db_account = get_db_account(account_name, account_config['session_name'])
            setup_handlers(client, account_config, account_name, db_account, text_watch_rules, media_watch_rules)
            clients.append(client)
        else:
            logger.info(f"Account {account_config.get('name', 'Unnamed')} is disabled and will not be initialized.")
    if not clients:
        logger.critical("No accounts were successfully initialized. Exiting.")
        return
    logger.info(f"Successfully initialized {len(clients)} active accounts. Starting clients...")
    try:
        await asyncio.gather(*[client.run_until_disconnected() for client in clients])
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"An unexpected error occurred in main loop: {e}", exc_info=True)
    finally:
        logger.info("Disconnecting all clients...")
        for client in clients:
            if client.is_connected():
                await client.disconnect()
        logger.info("All clients disconnected. Exiting.")

if __name__ == '__main__':
    asyncio.run(main())

