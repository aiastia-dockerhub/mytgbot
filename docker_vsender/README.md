# 📹 视频分发 Bot (docker_vsender)

一个基于 python-telegram-bot 的 Telegram 视频分发机器人，支持从本地目录读取视频文件并广播给白名单用户。

## ✨ 功能特性

### 📹 视频发送
- 发送指定本地视频文件给所有白名单用户
- 批量发送 N 个未发送的视频
- 按文件夹批量发送视频
- 自动追踪视频发送状态（已发送/未发送）
- 支持自定义 Telegram API 突破文件大小限制

### 👥 用户管理
- 白名单机制：只有白名单用户才能接收视频
- 管理员可直接添加/移除/封禁用户
- 用户可发送 `/request` 请求加入，管理员通过内联按钮审批
- 自动检测用户拉黑 Bot 并标记状态

### 📂 视频管理
- 自动扫描本地视频目录
- 支持子文件夹分类
- 分页查看视频列表（标记已发送/未发送状态）
- 支持重新标记视频为未发送

## 🚀 快速开始

### 1. 准备配置

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 Bot Token 和管理员 ID
```

### 2. 准备视频文件

将视频文件放到 `videos/` 目录下：

```
videos/
├── video1.mp4
├── video2.mkv
├── folder_a/
│   ├── v3.mp4
│   └── v4.mp4
└── folder_b/
    └── v5.mp4
```

支持的视频格式：`.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.ts`, `.m4v`, `.rmvb`, `.rm`

### 3. Docker 部署

```bash
docker compose up -d
```

## ⚙️ 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `BOT_TOKEN` | ✅ | - | Telegram Bot Token |
| `ADMIN_USER_ID` | ✅ | - | 管理员用户ID（多个用逗号分隔） |
| `TELEGRAM_API_URL` | ❌ | - | 自定义 Telegram API URL（突破限制） |
| `VIDEO_ROOT` | ❌ | `/app/videos` | 本地视频目录 |
| `DB_PATH` | ❌ | `./data/vsender.db` | 数据库路径 |
| `SEND_CONCURRENCY` | ❌ | `5` | 发送并发数 |
| `BATCH_INTERVAL` | ❌ | `1.0` | 批次间间隔（秒） |
| `VIDEO_INTERVAL` | ❌ | `3.0` | 视频间间隔（秒） |
| `LIST_PAGE_SIZE` | ❌ | `20` | 列表每页数量 |

## 📖 命令列表

### 用户命令

| 命令 | 说明 |
|------|------|
| `/start` | 开始使用 |
| `/help` | 查看帮助 |
| `/status` | 查看自己的状态 |
| `/request` | 请求加入白名单 |
| `/myid` | 查看自己的用户ID |

### 管理员命令 - 用户管理

| 命令 | 说明 |
|------|------|
| `/adduser <ID> [备注]` | 添加用户到白名单 |
| `/removeuser <ID>` | 移除用户 |
| `/ban <ID>` | 封禁用户 |
| `/unban <ID>` | 解封用户 |
| `/listusers` | 列出所有用户 |
| `/pending` | 查看待审批请求 |

### 管理员命令 - 视频发送

| 命令 | 说明 | 示例 |
|------|------|------|
| `/send <文件名>` | 发送指定视频 | `/send video.mp4` |
| `/sendnext <数量>` | 发送N个未发送视频 | `/sendnext 10` |
| `/senddir <文件夹>` | 发送文件夹下视频 | `/senddir folder_a` |
| `/listvideos [页码]` | 列出所有视频 | `/listvideos 2` |
| `/listunsend [页码]` | 列出未发送视频 | `/listunsend` |
| `/dirs` | 列出子文件夹 | `/dirs` |
| `/markunsend <文件名>` | 标记为未发送 | `/markunsend video.mp4` |
| `/reload` | 重新扫描视频目录 | `/reload` |
| `/stats` | 查看统计信息 | `/stats` |

## 🔄 使用流程

1. **启动 Bot** → 自动扫描 `VIDEO_ROOT` 目录中的视频文件
2. **添加用户** → 用户发送 `/request` 或管理员 `/adduser`
3. **发送视频** → 使用 `/send`、`/sendnext` 或 `/senddir` 命令
4. **查看统计** → `/stats` 查看用户和视频统计
5. **新增视频** → 放入 `videos/` 目录后发送 `/reload` 重新扫描

## 📁 项目结构

```
docker_vsender/
├── .env.example          # 环境变量示例
├── docker-compose.yml    # Docker 编排
├── Dockerfile            # Docker 镜像
├── main.py               # 入口文件
├── config.py             # 配置管理
├── database.py           # 数据库操作
├── handlers.py           # 命令/消息处理器
├── sender.py             # 视频发送模块
├── requirements.txt      # Python 依赖
├── README.md             # 说明文档
├── data/
│   └── .gitignore
└── videos/               # 视频目录（需自行创建）