# 🤖 FileID Bot — Telegram 文件ID互转机器人

一个独立的 Telegram Bot，专注于 **图片/视频/音频/文档 ↔ 唯一代码** 的双向转换，支持集合管理与分页组发送。

## ✨ 功能特性

### 📌 单文件处理
- 发送图片/视频/音频/文档 → 获取带 bot 用户名的唯一代码
- 发送代码 → 自动 `send_media_group` 组发送对应文件
- 支持 `/getid` 回复消息获取文件代码

### 📦 集合功能
- `/create 名称` 创建集合，连续发送最多 **999** 个文件
- 获取集合时支持三种方式：
  - **全部发送** — 按类型分批 `send_media_group` 组发送
  - **自动发送** — 每 5 秒发送一组，可随时停止
  - **分页浏览** — 每页 5 个文件，带翻页按钮

### 🔒 安全特性
- 32 位随机码（base62），杜绝碰撞
- 支持 Fernet 对称加密存储 file_id
- 支持 Cython 编译为 `.so` 保护源码

### 🔄 兼容性
- 兼容旧格式 `$p` `$v` `$d` 的 file_id
- 转发消息自动识别并处理

## 🚀 快速开始

### Docker 部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/aiastia-dockerhub/mytgbot.git
cd mytgbot/docker_fileid

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 BOT_TOKEN

# 3. 启动
docker-compose up -d
```

### 手动部署

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
export BOT_TOKEN="your_bot_token"

# 3. 运行
python main.py
```

## ⚙️ 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `ADMIN_IDS` | ❌ | 管理员ID（逗号分隔） |
| `ENCRYPTION_KEY` | ❌ | Fernet 加密密钥 |
| `CODE_PREFIX` | ❌ | 自定义代码前缀（默认使用 bot 用户名，不带@） |

### 生成加密密钥

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 📋 命令列表

| 命令 | 说明 |
|------|------|
| `/start` `/help` | 使用说明 |
| `/create [名称]` | 创建集合（连续发文件） |
| `/done` | 完成集合 |
| `/cancel` | 取消操作 / 停止自动发送 |
| `/getid` | 回复消息获取文件代码 |
| `/mycol` | 查看我的集合列表 |
| `/delcol 代码` | 删除集合 |
| `/stats` | 管理员统计信息 |
| `/export` | 管理员导出数据 |

## 📝 代码格式

```
BotUsername_p:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567  ← 图片
BotUsername_v:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567  ← 视频
BotUsername_d:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567  ← 文档/音频
BotUsername_col:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567 ← 集合
```

可通过 `CODE_PREFIX` 环境变量自定义前缀，例如设置 `CODE_PREFIX=FID` 后代码格式为 `FID_p:xxx`。

## 🗄️ 数据库

使用 SQLite 存储，数据文件位于 `./data/fileid.db`。

### 表结构

- **file_mappings** — 文件代码映射
- **collections** — 集合信息
- **collection_items** — 集合文件关联

## 🔐 Cython 编译

```bash
# 安装 Cython
pip install cython

# 编译
python build.py build_ext --inplace

# 部署时只需 .so 文件 + loader.py
```

## 📤 发送逻辑

| 类型 | 发送方式 | 说明 |
|------|---------|------|
| 图片+视频 | `send_media_group` | 混排相册，最多10个/组 |
| 文档 | `send_media_group` | 文档组，最多10个/组 |
| 音频 | `send_media_group` | 音频组，最多10个/组 |

自动发送模式每 5 秒发送一组，组内按类型聚合。

## 📨 消息处理流程

### Handler 注册顺序（优先级从高到低）

```
1. 命令处理器        → /start, /help, /create 等
2. 转发的图片        → handle_forwarded_media
3. 转发的其他媒体    → handle_forwarded_media (视频/文档/音频/语音)
4. 转发的文字消息    → handle_forward
5. 图片消息          → handle_group_media (单独注册)
6. 其他媒体消息      → handle_group_media (视频/文档/音频/语音)
7. 文字消息          → handle_text (代码解析)
8. 回调按钮          → button_callback (内联键盘)
9. 全局错误处理器    → error_handler
```

### 各消息类型的完整处理链

#### 🖼 单张图片（直接发送）

```
用户发送图片
  → filters.PHOTO 匹配
  → handle_group_media()
    → media_group_id 为 None（单张）
    → handle_attachment()
      → _extract_file_info(message)
        → message.photo[len(message.photo) - 1]  获取最大尺寸图片
      → save_file()  保存到数据库
      → 回复: "✅ 🖼 图片已保存！代码: BotName_p:xxxxx"
```

#### 🖼🖼 图片组（一次发送多张）

```
用户一次选择多张图片发送
  → filters.PHOTO 匹配（每张图片触发一次）
  → handle_group_media()
    → media_group_id 有值（同一组）
    → 收集到 pending_media_groups，等待 2 秒
    → _save_media_messages()  逐个保存
    → 回复: "✅ 媒体组已保存！共 N 个文件：
             BotName_p:xxxxx1
             BotName_p:xxxxx2
             ..."
```

#### 🎬 单个视频（直接发送）

```
用户发送视频
  → filters.VIDEO 匹配
  → handle_group_media()
    → media_group_id 为 None
    → handle_attachment()
      → _extract_file_info(message)
        → message.video.file_id
      → save_file()
      → 回复: "✅ 🎬 视频已保存！代码: BotName_v:xxxxx"
```

#### 🎬🎬 视频组（一次发送多个视频）

```
用户一次选择多个视频发送
  → filters.VIDEO 匹配（每个视频触发一次）
  → handle_group_media()
    → media_group_id 有值
    → 收集到 pending_media_groups，等待 2 秒
    → _save_media_messages()
    → 回复所有代码
```

#### 📄 文档 / 🎵 音频 / 🎤 语音（直接发送）

```
用户发送文档/音频/语音
  → filters.Document.ALL / filters.AUDIO / filters.VOICE 匹配
  → handle_group_media()
    → 无 media_group_id → handle_attachment()
    → 有 media_group_id → 收集后批量保存
    → 文档代码前缀: d, 音频/语音代码前缀也是: d
```

#### 💬 纯文字消息（代码解析）

```
用户发送文字
  → filters.TEXT & ~filters.COMMAND 匹配
  → handle_text()
    → 解析文件代码:   BotName_p:xxx / BotName_v:xxx / BotName_d:xxx
    → 解析集合代码:   BotName_col:xxx
    → 解析旧格式代码: $p xxx / $v xxx / $d xxx
    → 都不匹配 → 回复: "❓ 未识别的输入"

    文件代码 → get_file() → send_file_group() 发送文件
    集合代码 → get_collection() → 显示内联键盘（全部发送/自动发送/分页浏览）
    旧格式   → 直接用 file_id 发送
```

#### ↔️ 转发单张图片

```
用户转发一条含图片的消息
  → filters.FORWARDED & filters.PHOTO 匹配
  → handle_forwarded_media()
    → media_group_id 为 None
    → handle_attachment()
    → 与直接发送图片相同，保存并返回代码
```

#### ↔️ 转发图片组/视频组

```
用户转发多条媒体消息
  → filters.FORWARDED & filters.PHOTO/VIDEO 匹配
  → handle_forwarded_media()
    → media_group_id 有值
    → 收集到 pending_forward_groups，等待 2 秒
    → _save_media_messages()  保存所有文件
    → 自动创建集合（名称: "转发组_MMDDHHmm"）
    → 回复集合代码 + 各文件代码 + 内联键盘
```

#### ↔️ 转发文字消息

```
用户转发一条纯文字消息
  → filters.FORWARDED & filters.TEXT 匹配
  → handle_forward()
    → 含媒体 → handle_attachment()
    → 含文字 → handle_text()
    → 都没有 → 回复: "请转发包含媒体的消息"
```

#### 🔘 内联按钮回调

```
用户点击按钮
  → CallbackQueryHandler 匹配
  → button_callback()
    → s|key   → _send_paginated()  分页发送（从第1页开始）
    → a|key   → _auto_send()       自动发送（每组间隔5秒）
    → p|key|n → _send_page()       分页浏览（仅列表，不发送）
    → sn|key|n → _send_paginated() 发送下一页
    → stop_auto → 停止自动发送
```

### ⚠️ Cython 编译注意事项

由于代码使用 Cython 编译为 `.so` 文件，需注意以下限制：

- **禁止使用负索引**：`photo[-1]` 在 Cython 中会导致段错误（segfault），必须使用 `photo[len(photo) - 1]`
- **异常处理**：Cython 不会自动将所有 Python 异常转为 Python 异常对象，段错误会直接崩溃
- 编译警告 `array subscript -1 is below array bounds` 即表示此问题

## 📄 License

MIT
