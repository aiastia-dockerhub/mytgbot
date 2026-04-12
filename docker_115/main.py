# Tg bot + 115 磁力推送示例
import os
import json
import time
import logging
import hashlib
import base64
import string
import secrets
import asyncio
import requests
import qrcode
import io
import qrcode_terminal
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from dotenv import load_dotenv

# 尝试加载 .env 文件（如果存在）
load_dotenv(override=True)

# 配置日志
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 从环境变量或 .env 文件获取配置
def get_config(key, default=None):
    """获取配置，优先从 .env 文件读取，如果没有则从环境变量读取"""
    value = os.getenv(key, default)
    logger.info(f"Loading config {key}: {'*' * len(str(value)) if 'TOKEN' in key else value}")
    return value

# 配置
CLIENT_ID = int(get_config("CLIENT_ID", "100195135"))  # 115 client_id
USER_TOKEN_DIR = get_config("USER_TOKEN_DIR", "user_tokens")
ADMIN_IDS = [int(id.strip()) for id in get_config("ADMIN_IDS", "").split(",") if id.strip()]

# 网络和重试配置
REQUEST_TIMEOUT = int(get_config("REQUEST_TIMEOUT", "30"))          # 请求超时时间（秒）
MAX_REFRESH_RETRIES = int(get_config("MAX_REFRESH_RETRIES", "3"))   # Token 刷新最大重试次数
TOKEN_REFRESH_INTERVAL = int(get_config("TOKEN_REFRESH_INTERVAL", "180"))  # 后台刷新间隔（秒）
TOKEN_EXPIRY_BUFFER = int(get_config("TOKEN_EXPIRY_BUFFER", "300")) # Token 过期前提前刷新时间（秒）

# API URLs
AUTH_DEVICE_CODE_URL = "https://passportapi.115.com/open/authDeviceCode"
QRCODE_STATUS_URL = "https://qrcodeapi.115.com/get/status/"
DEVICE_CODE_TO_TOKEN_URL = "https://passportapi.115.com/open/deviceCodeToToken"
REFRESH_TOKEN_URL = "https://passportapi.115.com/open/refreshToken"
MAGNET_API_URL = "https://proapi.115.com/open/offline/add_task_urls"

# 定义对话状态
BINDING = 1

def user_token_file(user_id):
    os.makedirs(USER_TOKEN_DIR, exist_ok=True)
    return os.path.join(USER_TOKEN_DIR, f"{user_id}.json")

def read_token(user_id):
    try:
        with open(user_token_file(user_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_token(user_id, token_data):
    # 记录最后刷新时间，用于判断 token 是否即将过期
    token_data["last_refresh_time"] = int(time.time())
    with open(user_token_file(user_id), "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=2)

def generate_code_verifier(length=128):
    allowed_chars = string.ascii_letters + string.digits + "-._~"
    return ''.join(secrets.choice(allowed_chars) for _ in range(length))

def generate_code_challenge(verifier):
    sha = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha).rstrip(b"=").decode()

def is_token_near_expiry(token_info):
    """检查 token 是否即将过期"""
    last_refresh = token_info.get("last_refresh_time", 0)
    expires_in = token_info.get("expires_in", 7200)
    elapsed = int(time.time()) - last_refresh
    return elapsed > (expires_in - TOKEN_EXPIRY_BUFFER)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("欢迎使用 115 推送 Bot。请使用 /bind 开始绑定你的账号。")

async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 检查是否已绑定
    token_info = read_token(user_id)
    if token_info:
        await update.message.reply_text("你已经绑定过账号了。如果需要重新绑定，请先使用 /unbind 解绑。")
        return ConversationHandler.END

    # 生成新的二维码
    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier)

    try:
        resp = requests.post(AUTH_DEVICE_CODE_URL, data={
            "client_id": CLIENT_ID,
            "code_challenge": challenge,
            "code_challenge_method": "sha256"
        }, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get device code: {e}")
        await update.message.reply_text("网络请求失败，请稍后重试。")
        return ConversationHandler.END

    result = resp.json()
    if result.get("code") != 0:
        await update.message.reply_text("获取二维码失败。")
        return ConversationHandler.END

    data = result["data"]
    
    # 生成二维码图片
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data["qrcode"])
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # 将图片转换为字节流
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    
    # 发送二维码图片给用户
    await update.message.reply_photo(bio, caption="请使用115客户端扫描二维码。\n二维码有效期为5分钟，过期后将自动刷新。\n如果想取消绑定，请发送 /cancel")

    # 保存状态到上下文
    bind_data = {
        'verifier': verifier,
        'challenge': challenge,
        'data': data,
        'retry_count': 0,
        'last_check_time': time.time()
    }
    context.user_data['bind_data'] = bind_data
    
    # 启动轮询任务
    context.job_queue.run_repeating(
        check_qr_status,
        interval=5,
        first=5,
        data={
            'user_id': user_id,
            'bind_data': bind_data
        }
    )
    
    return BINDING

async def check_qr_status(context: ContextTypes.DEFAULT_TYPE):
    """定期检查二维码状态"""
    job = context.job
    user_id = job.data['user_id']
    bind_data = job.data['bind_data']
    
    if not bind_data:
        logger.error(f"No bind data found for user {user_id}")
        job.schedule_removal()
        return
    
    # 检查二维码状态
    try:
        status = requests.get(QRCODE_STATUS_URL, params={
            "uid": bind_data['data']["uid"],
            "time": bind_data['data']["time"],
            "sign": bind_data['data']["sign"]
        }, timeout=REQUEST_TIMEOUT)
        
        if status.status_code != 200:
            logger.error(f"QR status check failed with status code: {status.status_code}")
            await context.bot.send_message(chat_id=user_id, text="检查二维码状态失败，请重试。")
            job.schedule_removal()
            return
            
        status_data = status.json()
        if not status_data or "data" not in status_data:
            logger.error(f"Invalid QR status response: {status.text}")
            await context.bot.send_message(chat_id=user_id, text="二维码状态检查返回无效数据，请重试。")
            job.schedule_removal()
            return
            
        qr_status = status_data["data"].get("status")
        logger.info(f"QR status for user {user_id}: {qr_status}")
        
        if qr_status == 1:
            # 等待扫描
            return
            
        elif qr_status == 2:
            # 扫码成功，获取token
            token_resp = requests.post(DEVICE_CODE_TO_TOKEN_URL, data={
                "uid": bind_data['data']["uid"],
                "code_verifier": bind_data['verifier']
            }, timeout=REQUEST_TIMEOUT)
            
            if token_resp.status_code != 200:
                logger.error(f"Token request failed with status code: {token_resp.status_code}")
                await context.bot.send_message(chat_id=user_id, text="获取访问令牌失败，请重试。")
                job.schedule_removal()
                return
                
            token_data = token_resp.json()
            if token_data.get("code") == 0:
                write_token(user_id, token_data["data"])
                await context.bot.send_message(chat_id=user_id, text="✅ 绑定成功！现在你可以发送磁力链接了。")
                job.schedule_removal()
                return
            else:
                error_msg = token_data.get("message", "未知错误")
                logger.error(f"Token request failed: {error_msg}")
                await context.bot.send_message(chat_id=user_id, text=f"绑定失败：{error_msg}，请重试。")
                job.schedule_removal()
                return
                
        elif qr_status == 3:
            # 二维码过期，重新获取
            bind_data['retry_count'] += 1
            if bind_data['retry_count'] >= 3:
                await context.bot.send_message(chat_id=user_id, text="❌ 二维码已过期且达到最大重试次数，请重新使用 /bind 命令。")
                job.schedule_removal()
                return
                
            # 重新获取二维码
            resp = requests.post(AUTH_DEVICE_CODE_URL, data={
                "client_id": CLIENT_ID,
                "code_challenge": bind_data['challenge'],
                "code_challenge_method": "sha256"
            }, timeout=REQUEST_TIMEOUT)
            
            if resp.status_code != 200:
                logger.error(f"QR refresh failed with status code: {resp.status_code}")
                await context.bot.send_message(chat_id=user_id, text="刷新二维码失败，请重试。")
                job.schedule_removal()
                return
                
            result = resp.json()
            if result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                logger.error(f"QR refresh failed: {error_msg}")
                await context.bot.send_message(chat_id=user_id, text=f"刷新二维码失败：{error_msg}，请重试。")
                job.schedule_removal()
                return
                
            bind_data['data'] = result["data"]
            
            # 生成新的二维码图片
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(bind_data['data']["qrcode"])
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            bio = io.BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            
            await context.bot.send_photo(
                chat_id=user_id,
                photo=bio,
                caption=f"🔄 二维码已刷新，请重新扫描。\n这是第 {bind_data['retry_count'] + 1} 次尝试，还剩 {3 - bind_data['retry_count'] - 1} 次机会。\n如果想取消绑定，请发送 /cancel"
            )
            
    except requests.exceptions.RequestException as e:
        logger.warning(f"Network error while checking QR status (will retry next cycle): {str(e)}")
        # 网络错误不立即移除 job，等待下次轮询自动重试
    except Exception as e:
        logger.error(f"Unexpected error while checking QR status: {str(e)}")
        # 仅在严重错误时才移除 job

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 检查是否有正在进行的绑定过程
    if 'bind_data' not in context.user_data:
        await update.message.reply_text("当前没有正在进行的绑定过程。")
        return ConversationHandler.END
        
    # 清除绑定数据
    context.user_data.pop('bind_data', None)
    await update.message.reply_text("已取消绑定过程。")
    return ConversationHandler.END

async def handle_binding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bind_data = context.user_data.get('bind_data')
    
    if not bind_data:
        await update.message.reply_text("绑定过程已结束，请重新使用 /bind 命令。")
        return ConversationHandler.END

    # 检查二维码状态
    try:
        status = requests.get(QRCODE_STATUS_URL, params={
            "uid": bind_data['data']["uid"],
            "time": bind_data['data']["time"],
            "sign": bind_data['data']["sign"]
        }, timeout=REQUEST_TIMEOUT).json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error checking QR status: {e}")
        await update.message.reply_text("网络请求失败，请稍后重试。")
        return BINDING
    
    if status["data"].get("status") == 2:
        # 扫码成功，获取token
        try:
            token_resp = requests.post(DEVICE_CODE_TO_TOKEN_URL, data={
                "uid": bind_data['data']["uid"],
                "code_verifier": bind_data['verifier']
            }, timeout=REQUEST_TIMEOUT).json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting token: {e}")
            await update.message.reply_text("网络请求失败，请稍后重试。")
            return BINDING

        if token_resp.get("code") == 0:
            write_token(user_id, token_resp["data"])
            await update.message.reply_text("绑定成功！现在你可以发送磁力链接了。")
            return ConversationHandler.END
        else:
            await update.message.reply_text("绑定失败，请重试。")
            return ConversationHandler.END
            
    elif status["data"].get("status") == 3:
        # 二维码过期，重新获取
        bind_data['retry_count'] += 1
        if bind_data['retry_count'] >= 3:
            await update.message.reply_text("二维码已过期且达到最大重试次数，请重新使用 /bind 命令。")
            return ConversationHandler.END
            
        # 重新获取二维码
        try:
            resp = requests.post(AUTH_DEVICE_CODE_URL, data={
                "client_id": CLIENT_ID,
                "code_challenge": bind_data['challenge'],
                "code_challenge_method": "sha256"
            }, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error refreshing QR code: {e}")
            await update.message.reply_text("网络请求失败，请稍后重试。")
            return BINDING

        result = resp.json()
        if result.get("code") != 0:
            await update.message.reply_text("重新获取二维码失败。")
            return ConversationHandler.END
            
        bind_data['data'] = result["data"]
        
        # 生成新的二维码图片
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(bind_data['data']["qrcode"])
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        await update.message.reply_photo(bio, caption=f"二维码已刷新，请重新扫描。\n这是第 {bind_data['retry_count'] + 1} 次尝试，还剩 {3 - bind_data['retry_count'] - 1} 次机会。\n如果想取消绑定，请发送 /cancel")
    
    return BINDING

async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token_file = user_token_file(user_id)
    
    if os.path.exists(token_file):
        os.remove(token_file)
        await update.message.reply_text("已成功解绑账号。")
    else:
        await update.message.reply_text("你还没有绑定账号。")

def _do_refresh_token(user_id, token_info):
    """同步刷新用户 token，带重试和指数退避"""
    for attempt in range(MAX_REFRESH_RETRIES):
        try:
            refresh_resp = requests.post(REFRESH_TOKEN_URL, data={
                "client_id": CLIENT_ID,
                "refresh_token": token_info.get("refresh_token")
            }, timeout=REQUEST_TIMEOUT)
            
            if refresh_resp.status_code == 200:
                refresh_data = refresh_resp.json()
                if refresh_data.get("code") == 0:
                    token_info["access_token"] = refresh_data["data"]["access_token"]
                    token_info["refresh_token"] = refresh_data["data"]["refresh_token"]
                    token_info["expires_in"] = refresh_data["data"].get("expires_in", 7200)
                    write_token(user_id, token_info)
                    logger.info(f"Token refreshed successfully for user {user_id} on attempt {attempt + 1}")
                    return True
                else:
                    error_msg = refresh_data.get("message", "未知错误")
                    logger.warning(f"Token refresh API error for user {user_id}: {error_msg} (attempt {attempt + 1}/{MAX_REFRESH_RETRIES})")
            else:
                logger.warning(f"Token refresh HTTP {refresh_resp.status_code} for user {user_id} (attempt {attempt + 1}/{MAX_REFRESH_RETRIES})")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error refreshing token for user {user_id}: {e} (attempt {attempt + 1}/{MAX_REFRESH_RETRIES})")
        except Exception as e:
            logger.error(f"Unexpected error refreshing token for user {user_id}: {e} (attempt {attempt + 1}/{MAX_REFRESH_RETRIES})")
        
        # 指数退避：1s, 2s, 4s...
        if attempt < MAX_REFRESH_RETRIES - 1:
            wait_time = 2 ** attempt
            logger.info(f"Retrying token refresh for user {user_id} in {wait_time}s...")
            time.sleep(wait_time)
    
    logger.error(f"Token refresh failed for user {user_id} after {MAX_REFRESH_RETRIES} attempts")
    return False

async def refresh_user_token_async(user_id, token_info):
    """异步刷新用户 token（在线程池中运行同步代码，不阻塞事件循环）"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_refresh_token, user_id, token_info)

def refresh_user_token(user_id, token_info):
    """同步刷新用户 token（用于同步上下文）"""
    return _do_refresh_token(user_id, token_info)

def _sync_background_refresh_all_tokens():
    """同步后台刷新所有用户的 token（在线程池中运行）"""
    logger.info("Starting background token refresh cycle...")
    
    if not os.path.exists(USER_TOKEN_DIR):
        return
    
    token_files = [f for f in os.listdir(USER_TOKEN_DIR) if f.endswith('.json')]
    if not token_files:
        return
    
    refreshed = 0
    failed = 0
    skipped = 0
    
    for token_file in token_files:
        try:
            user_id = int(token_file.replace('.json', ''))
        except ValueError:
            logger.warning(f"Skipping invalid token file: {token_file}")
            continue
        
        try:
            token_info = read_token(user_id)
            if not token_info:
                continue
            
            # 检查是否即将过期
            if not is_token_near_expiry(token_info):
                skipped += 1
                logger.debug(f"Token for user {user_id} is still valid, skipping refresh")
                continue
            
            logger.info(f"Token for user {user_id} is near expiry, refreshing...")
            success = _do_refresh_token(user_id, token_info)
            if success:
                refreshed += 1
            else:
                failed += 1
                logger.warning(f"Background refresh failed for user {user_id}, will retry next cycle")
                # 注意：不删除 token，等下次循环再试
                
        except Exception as e:
            logger.error(f"Error processing token for user {user_id}: {e}")
            # 不删除 token，等下次循环再试
    
    logger.info(f"Background refresh cycle complete: refreshed={refreshed}, failed={failed}, skipped={skipped}")

async def background_refresh_all_tokens(context: ContextTypes.DEFAULT_TYPE):
    """后台定时刷新所有用户的 token（异步包装器）"""
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_background_refresh_all_tokens)
    except Exception as e:
        logger.error(f"Error in background token refresh: {e}")
        # 不要让异常终止整个循环

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logger.error(f"Exception while handling an update: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "抱歉，处理您的请求时出现错误。请稍后重试。"
            )
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

async def handle_magnet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理磁力链接"""
    if not update or not update.effective_user:
        logger.warning("Received update without user information")
        return

    user_id = update.effective_user.id
    token_info = read_token(user_id)
    if not token_info:
        await update.message.reply_text("你还没有绑定账号，请先使用 /bind")
        return

    magnet = update.message.text.strip()
    if not magnet.startswith("magnet:?"):
        await update.message.reply_text("请发送正确的磁力链接，以 magnet:? 开头")
        return

    try:
        # 仅在 token 即将过期时才刷新，避免每次请求都刷新
        if is_token_near_expiry(token_info):
            logger.info(f"Token for user {user_id} is near expiry, refreshing before magnet request...")
            refresh_ok = await refresh_user_token_async(user_id, token_info)
            if not refresh_ok:
                # 刷新失败，但旧 token 可能还有效，继续尝试
                logger.warning(f"Token refresh failed for user {user_id}, trying with existing token")

        headers = {
            "Authorization": f"Bearer {token_info['access_token']}"
        }
        logger.debug(f"Sending magnet request for user {user_id}")
        
        resp = requests.post(MAGNET_API_URL, data={
            "urls": magnet,
            "wp_path_id": "0"  # 默认保存到根目录
        }, headers=headers, timeout=REQUEST_TIMEOUT)
        
        # 如果返回 401，说明 token 确实失效了，尝试刷新后重试
        if resp.status_code == 401:
            logger.warning(f"Got 401 for user {user_id}, attempting token refresh and retry...")
            refresh_ok = await refresh_user_token_async(user_id, token_info)
            if refresh_ok:
                headers["Authorization"] = f"Bearer {token_info['access_token']}"
                resp = requests.post(MAGNET_API_URL, data={
                    "urls": magnet,
                    "wp_path_id": "0"
                }, headers=headers, timeout=REQUEST_TIMEOUT)
            else:
                await update.message.reply_text("❌ 登录已过期且刷新失败，请使用 /bind 重新绑定账号。")
                return
        
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("application/json"):
            result = resp.json()
            logger.debug(f"API Response: {result}")
            
            if result.get("state"):
                if result.get("data") and result["data"][0].get("state"):
                    await update.message.reply_text("✅ 磁力链接已成功添加到 115 离线下载。")
                else:
                    error_msg = result["data"][0].get("message", "未知错误") if result.get("data") else "未知错误"
                    await update.message.reply_text(f"添加失败：{error_msg}")
            else:
                error_msg = result.get("message", "未知错误")
                await update.message.reply_text(f"添加失败：{error_msg}")
        else:
            await update.message.reply_text(f"添加任务失败：服务器返回了非预期的响应 (HTTP {resp.status_code})")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request Error: {str(e)}")
        await update.message.reply_text(f"添加任务失败：网络请求错误，请稍后重试。")
    except json.JSONDecodeError as e:
        logger.error(f"JSON Parse Error: {str(e)}")
        await update.message.reply_text("添加任务失败：服务器响应格式错误")
    except Exception as e:
        logger.error(f"Unexpected Error: {str(e)}")
        await update.message.reply_text(f"添加任务失败：请稍后重试。")

if __name__ == "__main__":
    import sys

    # 从环境变量或 .env 文件获取 Telegram Bot Token
    TOKEN = get_config("BOT_TOKEN")
    if not TOKEN:
        logger.error("BOT_TOKEN not found in environment variables or .env file")
        sys.exit("请设置 BOT_TOKEN 环境变量或在 .env 文件中配置")

    app = ApplicationBuilder().token(TOKEN).build()

    # 创建对话处理器
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("bind", bind)],
        states={
            BINDING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_binding)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    # 添加错误处理器
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("unbind", unbind))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_magnet))

    # 注册后台 token 刷新任务
    app.job_queue.run_repeating(
        background_refresh_all_tokens,
        interval=TOKEN_REFRESH_INTERVAL,
        first=60,  # 启动后60秒开始首次刷新
    )
    logger.info(f"Background token refresh job registered (interval: {TOKEN_REFRESH_INTERVAL}s)")

    logger.info("Starting bot...")
    app.run_polling()