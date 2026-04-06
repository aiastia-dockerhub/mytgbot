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
@BotUsername_p:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567  ← 图片
@BotUsername_v:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567  ← 视频
@BotUsername_d:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567  ← 文档/音频
@BotUsername_col:a8Kj7xQm3nRt4wBk9mN2pLXY8zQn567 ← 集合
```

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

## 📄 License

MIT