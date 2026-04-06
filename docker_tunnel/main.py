"""
Gost 隧道管理 Telegram Bot
通过 gost v3 REST API 管理服务器和隧道
"""
import logging
import os
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, CallbackContext

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 加载配置
from config import BOT_TOKEN, ADMIN_IDS
from db.database import init_db

# 导入命令处理函数
from modules.server_handlers import (
    add_server, verify_server, list_servers, server_info, del_server, check_server, cancel_server
)
from modules.proxy_handlers import (
    create_proxy, list_proxies, del_proxy, start_proxy, stop_proxy
)
from modules.tunnel_handlers import (
    create_tunnel, list_tunnels, tunnel_status, start_tunnel, stop_tunnel, del_tunnel
)
from modules.batch_handlers import (
    batch_add_servers, batch_check_servers
)
from modules.status_monitor import get_overview
from modules.admin import admin_only


@admin_only
async def help_command(update: Update, context: CallbackContext):
    """帮助命令"""
    overview = await get_overview()
    
    msg = (
        "🤖 *Gost 隧道管理 Bot*\n"
        f"📊 服务器: {overview['servers']} | 代理: {overview['proxies']} | 隧道: {overview['tunnels']} (活跃: {overview['active_tunnels']})\n\n"
        "📋 *服务器管理:*\n"
        "`/add_server <名称> <IP> [端口|用户名 密码]` — 添加服务器\n"
        "`/verify_server <名称>` — 验证服务器连通性\n"
        "`/list_servers` — 列出所有服务器\n"
        "`/server_info <名称>` — 查看服务器详情\n"
        "`/del_server <名称>` — 删除服务器\n"
        "`/cancel_server <名称>` — 取消添加（输错时使用）\n"
        "`/check_server <名称>` — 检查服务器状态\n\n"
        "📡 *代理管理（单服务器）:*\n"
        "`/create_proxy <名称> <服务器> <协议> [端口]` — 创建代理\n"
        "`/list_proxies` — 列出所有代理\n"
        "`/start_proxy <名称>` — 启动代理\n"
        "`/stop_proxy <名称>` — 停止代理\n"
        "`/del_proxy <名称>` — 删除代理\n\n"
        "🔗 *隧道管理（多服务器链路）:*\n"
        "`/create_tunnel <名称> <协议> <端口> <服务器1> <服务器2> ...` — 创建隧道\n"
        "`/list_tunnels` — 列出所有隧道\n"
        "`/tunnel_status <名称>` — 查看隧道状态\n"
        "`/start_tunnel <名称>` — 启动隧道\n"
        "`/stop_tunnel <名称>` — 停止隧道\n"
        "`/del_tunnel <名称>` — 删除隧道\n\n"
        "📦 *批量操作:*\n"
        "`/batch_servers` — 批量添加服务器\n"
        "`/batch_check` — 批量检查服务器状态\n\n"
        "📖 *支持协议:*\n"
        "代理: `socks5`, `http`, `ss`, `tcp`, `socks5+tls`, `http+tls`\n"
        "隧道: `relay+tls`, `relay+ws+tls`, `relay`, `tcp`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


@admin_only
async def status_command(update: Update, context: CallbackContext):
    """系统状态概览"""
    overview = await get_overview()
    msg = (
        f"📊 *系统概览*\n\n"
        f"🖥 服务器: {overview['servers']}\n"
        f"📡 代理: {overview['proxies']}\n"
        f"🔗 隧道: {overview['tunnels']} (活跃: {overview['active_tunnels']})\n"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


def main():
    """启动 Bot"""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN 未设置！请在 .env 文件中配置。")
        return

    logger.info(f"Bot 启动中... ADMIN_IDS: {ADMIN_IDS}")

    # 初始化数据库
    init_db()
    logger.info("数据库初始化完成。")

    # 创建 Bot Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # ==================== 注册命令 ====================

    # 帮助 & 状态
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("start", help_command))
    application.add_handler(CommandHandler("status", status_command))

    # 服务器管理
    application.add_handler(CommandHandler("add_server", add_server))
    application.add_handler(CommandHandler("verify_server", verify_server))
    application.add_handler(CommandHandler("list_servers", list_servers))
    application.add_handler(CommandHandler("server_info", server_info))
    application.add_handler(CommandHandler("del_server", del_server))
    application.add_handler(CommandHandler("check_server", check_server))
    application.add_handler(CommandHandler("cancel_server", cancel_server))

    # 代理管理
    application.add_handler(CommandHandler("create_proxy", create_proxy))
    application.add_handler(CommandHandler("list_proxies", list_proxies))
    application.add_handler(CommandHandler("start_proxy", start_proxy))
    application.add_handler(CommandHandler("stop_proxy", stop_proxy))
    application.add_handler(CommandHandler("del_proxy", del_proxy))

    # 隧道管理
    application.add_handler(CommandHandler("create_tunnel", create_tunnel))
    application.add_handler(CommandHandler("list_tunnels", list_tunnels))
    application.add_handler(CommandHandler("tunnel_status", tunnel_status))
    application.add_handler(CommandHandler("start_tunnel", start_tunnel))
    application.add_handler(CommandHandler("stop_tunnel", stop_tunnel))
    application.add_handler(CommandHandler("del_tunnel", del_tunnel))

    # 批量操作
    application.add_handler(CommandHandler("batch_servers", batch_add_servers))
    application.add_handler(CommandHandler("batch_check", batch_check_servers))

    # 启动
    logger.info("Bot 已启动，开始轮询消息...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()