# 视频队列分发 Bot

将用户发送的视频/照片排队，慢慢分发给所有注册用户。

## 功能

- 📹 支持视频、照片、媒体组
- 📋 自动排队，逐一分发
- 🔒 可控制转发保护（`protect_content`）
- 👤 标注转发来源（用户ID/用户名）
- 🚫 自动检测拉黑并停止发送
- ⏰ 24小时活跃度检查

## 用户状态

| 状态 | 说明 |
|------|------|
| `active` | ✅ 正常接收 |
| `user_stopped` | ⏸️ 用户主动停止 |
| `system_stopped` | 🚫 系统停止（拉黑/不活跃） |

## 命令

| 命令 | 说明 |
|------|------|
| `/start` | 注册 / 查看帮助 |
| `/stop` | 暂停接收 |
| `/resume` | 恢复接收 |
| `/status` | 查看状态 |
| `/stats` | 管理员统计 |

## 部署

```bash
# 复制配置文件
cp .env.example .env
# 编辑 .env 填入 BOT_TOKEN 等

# 启动
docker compose up -d
```

## 文件结构

```
docker_vqueue/
├── config.py        # 配置
├── models.py        # 状态枚举/常量
├── database.py      # 数据库操作
├── handlers.py      # 命令/消息处理
├── sender.py        # 队列发送
├── scheduler.py     # 定时任务
├── main.py          # 入口
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example