# 🤖 Commander Bot — 指挥官 Bot

基于 Telegram Bot-to-Bot Communication 的智能 Bot 指挥官，使用 LLM 分析用户意图，自动路由到合适的子 Bot 处理请求。

## ✨ 功能特性

- 🧠 **LLM 意图识别** — 自动分析用户消息，判断应该交给哪个 Bot 处理
- 🔄 **Bot-to-Bot 通信** — 利用 Telegram 最新的 Bot-to-Bot Communication 功能
- 🛡️ **防循环机制** — 消息去重、频率限制、交互深度限制、超时保护
- 📋 **技能管理** — 通过 `skills.yml` 灵活配置和管理所有子 Bot
- 🔐 **管理员限制** — 仅管理员可使用指挥官

## 🏗️ 架构

```
用户 (私聊) → Commander Bot → LLM 意图分析
                                    ↓
                              路由到目标 Bot
                                    ↓
                           工作群组 (Bot-to-Bot)
                                    ↓
                           目标 Bot 处理并回复
                                    ↓
                           Commander Bot 收集回复
                                    ↓
                           转发回复给用户
```

## 📂 项目结构

```
docker_commander/
├── main.py               # 入口文件，命令和消息处理器
├── config.py              # 配置管理
├── llm_client.py          # LLM API 客户端（OpenAI 兼容）
├── intent_router.py       # 意图识别与路由
├── bot_manager.py         # Bot-to-Bot 通信管理
├── skills.yml             # 技能描述配置
├── requirements.txt       # Python 依赖
├── Dockerfile             # Docker 镜像
├── docker-compose.yml     # Docker 编排
├── .env.example           # 环境变量示例
├── README.md              # 说明文档
└── data/
    └── .gitignore
```

## 🚀 快速开始

### 1. 准备工作

1. **创建指挥官 Bot** — 在 @BotFather 创建新 Bot
2. **开启 Bot-to-Bot Communication** — 在 @BotFather 设置：
   ```
   /mybots → 选择 Bot → Bot Settings → Bot-to-Bot Communication → Enable
   ```
3. **创建工作群组** — 创建一个私有群组，将指挥官 Bot 和所有子 Bot 拉入
4. **获取群组 ID** — 可通过 @userinfobot 或将群组消息转发给 @RawDataBot 获取

### 2. 配置

```bash
# 复制环境变量文件
cp .env.example .env

# 编辑 .env 文件
# 必填项：
#   BOT_TOKEN       — 指挥官 Bot Token
#   ADMIN_IDS       — 你的 Telegram 用户 ID
#   WORK_GROUP_ID   — 工作群组 ID（负数）
#   LLM_API_URL     — LLM API 地址
#   LLM_API_KEY     — LLM API Key
```

### 3. 配置技能

编辑 `skills.yml`，将各 bot 的 `username` 替换为实际值，将需要启用的 bot 设为 `enabled: true`。

### 4. 部署

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f
```

## 📖 使用方式

### 智能路由（私聊指挥官 Bot）

直接向指挥官 Bot 发送消息：

- 发送 **贴纸** → 自动转发给 sticker2img bot 转为图片
- 发送 **"帮我搜索 xxx"** → LLM 判断意图并路由到对应 bot
- 发送 **"查隧道状态"** → 路由到 tunnel bot

### 管理命令

| 命令 | 说明 |
|------|------|
| `/start` | 查看帮助 |
| `/help` | 查看帮助 |
| `/bots` | 查看所有 Bot 状态 |
| `/status` | 查看当前路由状态 |
| `/reload` | 重新加载技能配置 |
| `/dispatch <bot_key> <命令>` | 手动向指定 Bot 发送命令 |

### 手动派发示例

```
/dispatch sticker2img /start
/dispatch tunnel /list_servers
/dispatch vsender /listvideos
```

## ⚙️ 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `BOT_TOKEN` | ✅ | - | 指挥官 Bot Token |
| `ADMIN_IDS` | ✅ | - | 管理员 ID（逗号分隔） |
| `WORK_GROUP_ID` | ✅ | - | 工作群组 ID |
| `LLM_API_URL` | ✅ | - | LLM API 地址 |
| `LLM_API_KEY` | ✅ | - | LLM API Key |
| `LLM_MODEL` | ❌ | `gpt-4o-mini` | LLM 模型名称 |
| `LLM_MAX_TOKENS` | ❌ | `512` | 最大 token 数 |
| `LLM_TEMPERATURE` | ❌ | `0.3` | 温度参数 |
| `RATE_LIMIT_PER_BOT` | ❌ | `1.0` | 每 bot 每秒消息数上限 |
| `MAX_INTERACTION_DEPTH` | ❌ | `5` | 最大交互深度 |
| `RESPONSE_TIMEOUT` | ❌ | `30` | 等待回复超时（秒） |
| `DEDUP_WINDOW` | ❌ | `60` | 消息去重窗口（秒） |

## ⚠️ 重要提醒

### Bot-to-Bot 通信设置

1. **在 @BotFather 开启 Bot-to-Bot Communication** — 不仅是指挥官 Bot，所有子 Bot 也需要开启
2. **将指挥官 Bot 的 user_id 加入子 Bot 的 ADMIN_IDS** — 因为指挥官代替你发送命令

### 防循环

Bot 遵循 Telegram 官方推荐的防循环措施：
- ✅ 消息去重
- ✅ 频率限制
- ✅ 交互深度限制
- ✅ 超时保护

## 🔧 支持的 LLM

任何兼容 OpenAI `/v1/chat/completions` 格式的 API：

- **OpenAI** — `https://api.openai.com/v1`
- **DeepSeek** — `https://api.deepseek.com/v1`
- **Ollama** — `http://localhost:11434/v1`
- **vLLM** — `http://localhost:8000/v1`
- **其他** — 任何兼容的 API

## 技术栈

- **Bot 框架**: python-telegram-bot v22+
- **LLM 客户端**: httpx (异步)
- **配置格式**: YAML
- **部署方式**: Docker