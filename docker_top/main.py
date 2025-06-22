import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from config import API_BASE, HIDE_CATEGORY_IDS, HIDE_LINK_IDS, HIDE_LINK_KEYWORDS, TOKEN
# 全局缓存变量
CATEGORIES_CACHE = None
LINKS_CACHE = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CATEGORIES_CACHE
    if CATEGORIES_CACHE is None:
        resp = requests.get(f"{API_BASE}/categories")
        cats = resp.json()
        CATEGORIES_CACHE = cats
    else:
        cats = CATEGORIES_CACHE
    # 过滤掉不想展示的分类
    cats = [cat for cat in cats if cat['id'] not in HIDE_CATEGORY_IDS]
    keyboard = [
        [InlineKeyboardButton(cat['name'], callback_data=f"cat_{cat['id']}")]
        for cat in cats
    ]
    await update.message.reply_text(
        "请选择一个分类：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LINKS_CACHE
    query = update.callback_query
    await query.answer()
    cat_id = query.data.replace("cat_", "")
    if cat_id in LINKS_CACHE:
        links = LINKS_CACHE[cat_id]
    else:
        resp = requests.get(f"{API_BASE}/links?category_id={cat_id}")
        links = resp.json()
        LINKS_CACHE[cat_id] = links
    # 过滤掉不想展示的链接
    links = [
        link for link in links
        if link['id'] not in HIDE_LINK_IDS
        and not any(kw in (link.get('title', '') + link.get('description', '') + link.get('url', '')) for kw in HIDE_LINK_KEYWORDS)
    ]
    if not links:
        await query.edit_message_text(
            "该分类下暂无链接。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回分类", callback_data="back_to_categories")]])
        )
        return
    msg = ""
    for idx, link in enumerate(links, 1):
        msg += f"{idx}. <b><a href='{link['url']}'>{link['title']}</a></b>\n"
        if link.get("description"):
            msg += f"    <i>{link['description']}</i>\n"
        msg += "\n"
    keyboard = [[InlineKeyboardButton("返回分类", callback_data="back_to_categories")]]
    await query.edit_message_text(msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(keyboard))

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CATEGORIES_CACHE
    query = update.callback_query
    await query.answer()
    if CATEGORIES_CACHE is None:
        resp = requests.get(f"{API_BASE}/categories")
        cats = resp.json()
        CATEGORIES_CACHE = cats
    else:
        cats = CATEGORIES_CACHE
    cats = [cat for cat in cats if cat['id'] not in HIDE_CATEGORY_IDS]
    keyboard = [
        [InlineKeyboardButton(cat['name'], callback_data=f"cat_{cat['id']}")]
        for cat in cats
    ]
    await query.edit_message_text(
        "请选择一个分类：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def clear_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CATEGORIES_CACHE, LINKS_CACHE
    CATEGORIES_CACHE = None
    LINKS_CACHE = {}
    await update.message.reply_text("缓存已清空！")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clearcache", clear_cache))
    app.add_handler(CallbackQueryHandler(category, pattern=r"^cat_\d+$"))
    app.add_handler(CallbackQueryHandler(back_to_categories, pattern="^back_to_categories$"))
    app.run_polling()

if __name__ == "__main__":
    main()