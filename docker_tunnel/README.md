# Gost 隧道管理 Telegram Bot

通过 Telegram Bot 管理 [gost v3](https://gost.run/) 隧道和代理服务，支持多服务器链路组网。

## 功能特性

- 🖥 **服务器管理** — 添加/删除/查看/批量添加服务器
- 📡 **代理服务** — 在单台服务器上创建 SOCKS5/HTTP/Shadowsocks 代理
- 🔗 **隧道组网** — 多台服务器组成加密隧道链路（relay+tls）
- 📦 **批量操作** — 批量添加服务器、批量检查状态
- 📊 **状态监控** — 实时检查服务器连通性和服务运行状态
- 🔐 **安全存储** — API 密码加密存储（AES-256）

## 架构

```
用户 (Telegram) ←→ Bot ←→ gost REST API ←→ 远程服务器
```

**单服务器代理：**
```
Client → 服务器:gost(SOCKS5/SS) → 目标网络
```

**多服务器隧道（relay+tls）：**
```
Client → Server1(入口) → Server2(中转) → Server3(出口) → 目标
```

## 快速开始

### 1. 服务器端部署 gost

在被管理的服务器上运行（推荐使用 Docker）：

```bash
docker run -d --name gost --restart=always --net=host \
  gogost/gost \
  -api "用户名:密码@:18080"
```

> ⚠️ `--net=host` 确保代理端口和 API 端口都可访问。API 默认端口 `18080`。

或者自定义密码（建议使用强密码）：

```bash
docker run -d --name gost --restart=always --net=host \
  gogost/gost \
  -api "gost_a1b2c3:Kx9#mP2\$vL5nQ8@wR3tY6jH4cF7dS1!z@:18080"
```

### 2. 部署 Bot

#### 方式一：Docker Compose（推荐）

1. 复制环境变量文件并编辑：

```bash
cp .env.example .env
```

2. 编辑 `.env` 文件：

```env
BOT_TOKEN=your_bot_token_here
ADMIN_IDS=123456789
ENCRYPTION_KEY=your_random_32_char_string
```

3. 启动：

```bash
docker-compose up -d
```

#### 方式二：手动运行

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 文件配置 BOT_TOKEN 等
python3 main.py
```

## Bot 命令

### 📋 服务器管理

| 命令 | 说明 |
|------|------|
| `/add_server <名称> <IP>` | 添加服务器（自动生成 API 密码） |
| `/add_server <名称> <IP> <端口>` | 指定 API 端口 |
| `/add_server <名称> <IP> <用户名> <密码> [端口]` | 自定义认证 |
| `/verify_server <名称>` | 验证服务器连通性 |
| `/list_servers` | 列出所有服务器 |
| `/server_info <名称>` | 查看服务器详情 |
| `/check_server <名称>` | 检查服务器状态 |
| `/del_server <名称>` | 删除服务器 |

### 📡 代理管理（单服务器）

| 命令 | 说明 |
|------|------|
| `/create_proxy <名称> <服务器> <协议> [端口]` | 创建代理服务 |
| `/list_proxies` | 列出所有代理 |
| `/start_proxy <名称>` | 启动代理 |
| `/stop_proxy <名称>` | 停止代理 |
| `/del_proxy <名称>` | 删除代理 |

**支持协议：** `socks5`, `http`, `ss`(Shadowsocks), `tcp`, `socks5+tls`, `http+tls`

### 🔗 隧道管理（多服务器链路）

| 命令 | 说明 |
|------|------|
| `/create_tunnel <名称> <协议> <端口> <服务器1> <服务器2> ...` | 创建隧道 |
| `/list_tunnels` | 列出所有隧道 |
| `/tunnel_status <名称>` | 查看隧道状态 |
| `/start_tunnel <名称>` | 启动隧道 |
| `/stop_tunnel <名称>` | 停止隧道 |
| `/del_tunnel <名称>` | 删除隧道 |

**支持协议：** `relay+tls`（推荐）, `relay+ws+tls`, `relay`, `tcp`

### 📦 批量操作

| 命令 | 说明 |
|------|------|
| `/batch_servers` | 批量添加服务器 |
| `/batch_check` | 批量检查所有服务器状态 |

### 📖 其他

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |
| `/start` | 查看帮助 |
| `/status` | 系统状态概览 |

## 使用示例

### 添加服务器并创建代理

```
/add_server HK-01 1.2.3.4
```

Bot 会返回部署命令和自动生成的 API 密码。在服务器上执行命令后：

```
/verify_server HK-01
/create_proxy hk-proxy HK-01 socks5 1080
```

### 创建多服务器隧道

```
/create_tunnel mytunnel relay+tls 8080 HK-01 US-02 JP-03
```

这将创建链路：`HK-01(入口) → US-02(中转) → JP-03(出口)`

### 批量添加服务器

```
/batch_servers
HK-01,1.2.3.4
US-02,2.3.4.5
JP-03,3.4.5.6,18080,user,pass
```

## 项目结构

```
docker_tunnel/
├── .env.example          # 环境变量模板
├── docker-compose.yml    # Docker 编排
├── Dockerfile            # 镜像构建
├── requirements.txt      # Python 依赖
├── main.py               # Bot 入口
├── config.py             # 配置管理
├── db/
│   ├── database.py       # 数据库连接
│   └── models.py         # 数据模型 (Server, Proxy, Tunnel, TunnelNode)
├── modules/
│   ├── admin.py          # 管理员权限检查
│   ├── gost_api.py       # gost v3 REST API 客户端
│   ├── server_handlers.py # 服务器管理命令
│   ├── proxy_handlers.py  # 代理管理命令
│   ├── tunnel_handlers.py # 隧道管理命令
│   ├── batch_handlers.py  # 批量操作命令
│   └── status_monitor.py  # 状态监控
└── data/
    └── .gitignore
```

## 数据库模型

- **Server** — 服务器信息（IP、API 认证、状态）
- **Proxy** — 代理服务（协议、端口、关联服务器）
- **Tunnel** — 隧道（协议、端口、活跃状态）
- **TunnelNode** — 隧道节点（有序服务器列表，角色：entry/relay/exit）

## 安全说明

- API 密码使用 AES-256 加密存储
- 所有操作需要管理员权限验证
- 部署命令中包含强随机密码（32位，含大小写+数字+特殊字符）
- gost API 支持 Basic Auth 认证
- 隧道通信支持 TLS 加密

## 技术栈

- **Bot 框架**: python-telegram-bot v20+
- **数据库**: SQLAlchemy + SQLite
- **HTTP 客户端**: aiohttp（异步）
- **加密**: cryptography (Fernet)
- **隧道引擎**: gost v3 (Docker 部署)