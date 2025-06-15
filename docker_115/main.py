# Tg bot + 115 磁力推送示例
import os
import json
import time
import logging
import qrcode_terminal
import hashlib
import base64
import string
import secrets
import requests
import qrcode
import io
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
    except:
        return None

def write_token(user_id, token_data):
    with open(user_token_file(user_id), "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=2)

def generate_code_verifier(length=128):
    allowed_chars = string.ascii_letters + string.digits + "-._~"
    return ''.join(secrets.choice(allowed_chars) for _ in range(length))

def generate_code_challenge(verifier):
    sha = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha).rstrip(b"=").decode()

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

    resp = requests.post(AUTH_DEVICE_CODE_URL, data={
        "client_id": CLIENT_ID,
        "code_challenge": challenge,
        "code_challenge_method": "sha256"
    })
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
            'bind_data': bind_data  # 直接传递绑定数据
        }
    )
    
    return BINDING

async def check_qr_status(context: ContextTypes.DEFAULT_TYPE):
    """定期检查二维码状态"""
    job = context.job
    user_id = job.data['user_id']
    bind_data = job.data['bind_data']  # 从job数据中获取绑定数据
    
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
        })
        
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
            })
            
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
            })
            
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
        logger.error(f"Network error while checking QR status: {str(e)}")
        await context.bot.send_message(chat_id=user_id, text="网络错误，请检查网络连接后重试。")
        job.schedule_removal()
    except Exception as e:
        logger.error(f"Unexpected error while checking QR status: {str(e)}")
        await context.bot.send_message(chat_id=user_id, text="检查二维码状态时出现未知错误，请重试。")
        job.schedule_removal()

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
    status = requests.get(QRCODE_STATUS_URL, params={
        "uid": bind_data['data']["uid"],
        "time": bind_data['data']["time"],
        "sign": bind_data['data']["sign"]
    }).json()
    
    if status["data"].get("status") == 2:
        # 扫码成功，获取token
        token_resp = requests.post(DEVICE_CODE_TO_TOKEN_URL, data={
            "uid": bind_data['data']["uid"],
            "code_verifier": bind_data['verifier']
        }).json()
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
        resp = requests.post(AUTH_DEVICE_CODE_URL, data={
            "client_id": CLIENT_ID,
            "code_challenge": bind_data['challenge'],
            "code_challenge_method": "sha256"
        })
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

def refresh_user_token(user_id, token_info):
    """刷新用户的 token"""
    try:
        refresh_resp = requests.post(REFRESH_TOKEN_URL, data={
            "client_id": CLIENT_ID,
            "refresh_token": token_info.get("refresh_token")
        })
        
        if refresh_resp.status_code == 200:
            refresh_data = refresh_resp.json()
            if refresh_data.get("code") == 0:
                token_info["access_token"] = refresh_data["data"]["access_token"]
                token_info["refresh_token"] = refresh_data["data"]["refresh_token"]
                write_token(user_id, token_info)
                return True
        return False
    except Exception as e:
        print(f"Token refresh error: {str(e)}")
        return False

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logger.error(f"Exception while handling an update: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "抱歉，处理您的请求时出现错误。请稍后重试。"
        )

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
        # 刷新 token
        if not refresh_user_token(user_id, token_info):
            await update.message.reply_text("token 刷新失败，请重新绑定账号")
            return

        headers = {
            "Authorization": f"Bearer {token_info['access_token']}"
        }
        logger.debug(f"Request headers: {headers}")
        
        resp = requests.post(MAGNET_API_URL, data={
            "urls": magnet,
            "wp_path_id": "0"  # 默认保存到根目录
        }, headers=headers)
        
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("application/json"):
            result = resp.json()
            logger.debug(f"API Response: {result}")
            
            if result.get("state"):
                if result.get("data") and result["data"][0].get("state"):
                    await update.message.reply_text("磁力链接已成功添加到 115 离线下载。")
                else:
                    error_msg = result["data"][0].get("message", "未知错误") if result.get("data") else "未知错误"
                    await update.message.reply_text(f"添加失败：{error_msg}")
            else:
                error_msg = result.get("message", "未知错误")
                await update.message.reply_text(f"添加失败：{error_msg}")
        else:
            await update.message.reply_text("添加任务失败：服务器返回了非预期的响应")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request Error: {str(e)}")
        await update.message.reply_text(f"添加任务失败：网络请求错误 - {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON Parse Error: {str(e)}")
        logger.error(f"Raw Response: {resp.text}")
        await update.message.reply_text("添加任务失败：服务器响应格式错误")
    except Exception as e:
        logger.error(f"Unexpected Error: {str(e)}")
        await update.message.reply_text(f"添加任务失败：{str(e)}")

if __name__ == "__main__":
    import asyncio
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

    logger.info("Starting bot...")
    app.run_polling()