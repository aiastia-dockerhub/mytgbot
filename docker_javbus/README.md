# JavBus 磁力搜索 Telegram Bot

通过 [javbus-api](https://github.com/ovnrain/javbus-api) 获取影片信息和磁力链接的 Telegram Bot。

## 功能

- 🔍 单个影片磁力链接查询
- 👩 按演员获取全部影片磁力链接
- 🏷 按类别/导演/制作商/发行商/系列筛选
- 🔎 关键词搜索影片
- 🎬 影片详情（封面图、演员、类别等）
- 👤 演员信息卡片（头像、身高三围等）
- 🔒 仅管理员可用
- 🛡 Cython 编译保护源码

## 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/jav <番号>` | 查询单个影片磁力链接 | `/jav SSIS-406` |
| `/jav_star <演员id>` | 获取演员全部影片磁力链接 | `/jav_star 2xi` |
| `/jav_filter <类型> <值>` | 按类型筛选影片 | `/jav_filter genre 4` |
| `/jav_search <关键词>` | 搜索影片 | `/jav_search 三上` |
| `/movie <番号>` | 查看影片详情 | `/movie SSIS-406` |
| `/star <演员id>` | 查看演员信息 | `/star 2xi` |
| `/help` | 显示帮助信息 | |

**筛选类型**: `star`(演员) `genre`(类别) `director`(导演) `studio`(制作商) `label`(发行商) `series`(系列)

## 部署

### 前置条件

需要一个运行中的 [javbus-api](https://github.com/ovnrain/javbus-api) 服务。

```bash
docker pull ovnrain/javbus-api
docker run -d --name=javbus-api --restart=unless-stopped -p 3000:3000 ovnrain/javbus-api
```

### Docker Compose（推荐）

1. 创建 `.env` 文件：

```bash
cp .env.example .env
```

2. 编辑 `.env`，填写必要配置：

```env
BOT_TOKEN=你的Bot Token
ADMIN_IDS=你的Telegram用户ID
JAVBUS_API_URL=http://javbus-api地址:3000
```

3. 启动：

```bash
docker-compose up -d --build
```

### Docker 手动构建

```bash
docker build -t aiastia/mytgbot:javbus .
docker run -d --restart=unless-stopped \
  -e BOT_TOKEN=你的Token \
  -e ADMIN_IDS=你的ID \
  -e JAVBUS_API_URL=http://javbus-api:3000 \
  aiastia/mytgbot:javbus
```

### GitHub Actions

项目包含独立的 GitHub Action 工作流 (`.github/workflows/docker-javbus.yml`)：

1. 进入仓库的 Actions 页面
2. 选择 `docker-javbus` 工作流
3. 点击 `Run workflow`
4. 选择是否推送到 DockerHub
5. 镜像标签：`aiastia/mytgbot:javbus`

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `BOT_TOKEN` | ✅ | | Telegram Bot Token |
| `ADMIN_IDS` | ✅ | | 管理员用户ID（逗号分隔） |
| `JAVBUS_API_URL` | ✅ | | javbus-api 服务地址 |
| `JAVBUS_AUTH_TOKEN` | ❌ | | API 认证 Token |
| `DEFAULT_TYPE` | ❌ | `normal` | 影片类型：`normal`(有码) / `uncensored`(无码) |
| `MAGNET_SORT_BY` | ❌ | `size` | 磁力排序：`size` / `date` |
| `MAGNET_SORT_ORDER` | ❌ | `desc` | 排序方向：`desc` / `asc` |
| `MAX_CONCURRENT` | ❌ | `10` | 并发请求数 |
| `MAX_PAGES` | ❌ | `20` | 单次搜索最大页数 |
| `TZ` | ❌ | `Asia/Shanghai` | 时区 |

## 源码保护

Dockerfile 使用多阶段构建：

1. **Builder 阶段**：安装 Cython，将 `config.py` 和 `modules/*.py` 编译为 `.so` 共享库
2. **Runner 阶段**：只复制 `main.py`（入口）和编译后的 `.so` 文件

最终镜像中不包含 Python 源代码，无法直接查看业务逻辑。

## 演员ID 获取

访问 [javbus.com/star](https://www.javbus.com/star) 页面，URL 中的最后一段即为演员ID。

例如 `https://www.javbus.com/star/2xi` → 演员ID 为 `2xi`