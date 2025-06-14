import os
import math
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from orm_utils import SessionLocal
from orm_models import User, File

# 工具函数：分割长消息
MAX_TG_MSG_LEN = 4096
def split_message(text, max_length=MAX_TG_MSG_LEN):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

DB_PATH = './data/sent_files.db'
PAGE_SIZE = 10
BOT_USERNAME = None  # 由主程序注入
SS_PAGE_SIZE = 10

def set_bot_username(username):
    global BOT_USERNAME
    BOT_USERNAME = username

def get_user_vip_level(user_id):
    with SessionLocal() as session:
        user = session.query(User).filter_by(user_id=user_id).first()
        return user.vip_level if user else 0

def get_file_by_id(file_id):
    with SessionLocal() as session:
        file = session.query(File).filter_by(file_id=file_id).first()
        if file:
            return file.tg_file_id, file.file_path
        return None

def search_files_by_name(keyword):
    with SessionLocal() as session:
        results = session.query(File).filter(File.file_path.like(f"%{keyword}%")).order_by(File.file_id.desc()).all()
        return [(file.file_id, file.file_path, file.tg_file_id) for file in results]

def update_file_tg_id(file_id, tg_file_id):
    with SessionLocal() as session:
        file = session.query(File).filter_by(file_id=file_id).first()
        if file:
            file.tg_file_id = tg_file_id
            session.commit()

def build_search_keyboard(results, page, keyword):
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_results = results[start:end]
    keyboard = []
    for file_id, file_path, tg_file_id in page_results:
        filename = os.path.basename(file_path)
        # 按钮 callback_data: sget|file_id
        keyboard.append([InlineKeyboardButton(filename, callback_data=f"sget|{file_id}")])
    # 分页按钮
    total_pages = math.ceil(len(results) / PAGE_SIZE)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton('上一页', callback_data=f'spage|{keyword}|{page-1}'))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton('下一页', callback_data=f'spage|{keyword}|{page+1}'))
    if nav:
        keyboard.append(nav)
    return InlineKeyboardMarkup(keyboard)

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    vip_level = get_user_vip_level(user_id)
    if vip_level < 3:
        await update.message.reply_text('只有VIP3及以上用户才能使用此命令。')
        return
    if not context.args:
        await update.message.reply_text('用法：/s <关键词>')
        return
    keyword = ' '.join(context.args)
    results = search_files_by_name(keyword)
    if not results:
        await update.message.reply_text('未找到相关文件。')
        return
    reply_markup = build_search_keyboard(results, 0, keyword)
    await update.message.reply_text(f'搜索结果，共{len(results)}个文件：', reply_markup=reply_markup)

async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('|')
    if data[0] == 'spage':
        keyword = data[1]
        page = int(data[2])
        results = search_files_by_name(keyword)
        reply_markup = build_search_keyboard(results, page, keyword)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
    elif data[0] == 'sget':
        file_id = int(data[1])
        row = get_file_by_id(file_id)
        if not row:
            await query.answer('文件不存在', show_alert=True)
            return
        tg_file_id, file_path = row
        try:
            # 判断 file_id 前缀类型
            if tg_file_id and (tg_file_id.startswith('BQAC') or tg_file_id.startswith('CAAC') or tg_file_id.startswith('HDAA')):
                await query.message.reply_document(tg_file_id, caption=f'文件tg_file_id: {tg_file_id}')
            elif tg_file_id and tg_file_id.startswith('BAAC'):
                await query.message.reply_video(tg_file_id, caption=f'文件tg_file_id: {tg_file_id}')
            elif tg_file_id and tg_file_id.startswith('AgAC'):
                await query.message.reply_photo(tg_file_id, caption=f'文件tg_file_id: {tg_file_id}')
            elif tg_file_id is None or tg_file_id == '':
                # 没有 file_id，直接发本地文件，需判断文件类型
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                    with open(file_path, 'rb') as f:
                        msg = await query.message.reply_photo(f, caption='本地图片直传')
                        # 写入tg_file_id
                        new_file_id = msg.photo[-1].file_id if msg.photo else None
                elif ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                    with open(file_path, 'rb') as f:
                        msg = await query.message.reply_video(f, caption='本地视频直传')
                        new_file_id = msg.video.file_id
                elif os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        msg = await query.message.reply_document(f, caption='本地文件直传')
                        new_file_id = msg.document.file_id
                else:
                    await query.answer('文件丢失', show_alert=True)
                    return
                # 更新数据库
                if new_file_id:
                    update_file_tg_id(file_id, new_file_id)
            elif os.path.exists(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                    with open(file_path, 'rb') as f:
                        msg = await query.message.reply_photo(f, caption=f'文件tg_file_id: {tg_file_id}')
                        # 写入tg_file_id（如有变化）
                        new_file_id = msg.photo[-1].file_id if msg.photo else None
                elif ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                    with open(file_path, 'rb') as f:
                        msg = await query.message.reply_video(f, caption=f'文件tg_file_id: {tg_file_id}')
                        new_file_id = msg.video.file_id
                else:
                    with open(file_path, 'rb') as f:
                        msg = await query.message.reply_document(f, caption=f'文件tg_file_id: {tg_file_id}')
                        new_file_id = msg.document.file_id
                # 更新数据库
                if new_file_id and new_file_id != tg_file_id:
                    update_file_tg_id(file_id, new_file_id)
            else:
                await query.answer('文件丢失', show_alert=True)
                return
        except Exception as e:
            await query.answer(f'发送失败: {e}', show_alert=True)
        await query.answer()

async def ss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    vip_level = get_user_vip_level(user_id)
    if vip_level < 2:
        await update.message.reply_text('只有VIP2及以上用户才能使用此命令。')
        return
    if not context.args:
        await update.message.reply_text('用法：/ss <关键词>')
        return
    keyword = ' '.join(context.args)
    await send_ss_page(update, context, keyword, page=0, edit=False)

async def ss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('|')
    if len(data) == 3 and data[0] == 'sspage':
        keyword = data[1]
        page = int(data[2])
        await send_ss_page(update, context, keyword, page=page, edit=True)

async def send_ss_page(update, context, keyword, page=0, edit=False):
    results = search_files_by_name(keyword)
    total = len(results)
    if total == 0:
        msg = '未找到相关文件。'
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    start = page * SS_PAGE_SIZE
    end = start + SS_PAGE_SIZE
    page_rows = results[start:end]
    links = []
    for idx, (file_id, file_path, tg_file_id) in enumerate(page_rows, start+1):
        filename = os.path.basename(file_path)
        link = f'https://t.me/{BOT_USERNAME}?start=book_{file_id}'
        links.append(f'{idx}. <a href="{link}">{filename}</a>')
    msg = f'搜索结果，共{total}个文件：\n' + '\n'.join(links)
    # 分页按钮
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton('上一页', callback_data=f'sspage|{keyword}|{page-1}'))
    if end < total:
        buttons.append(InlineKeyboardButton('下一页', callback_data=f'sspage|{keyword}|{page+1}'))
    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode='HTML', disable_web_page_preview=True, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True, reply_markup=reply_markup)
