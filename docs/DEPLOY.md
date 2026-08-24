# DEPLOY.md — 部署与备份运维手册

> Mustdo 后端运维手册：新 VPS 部署、定时备份、灾难恢复。
> 部署路径示例用 `/opt/mustdo/backend`（下文简写 `$BACKEND`），实际以你的 VPS 为准。

## 环境总览

| 项 | 值 |
|----|----|
| API 域名 | `https://mustdo.doebkblcya.com`（微信小程序 request 合法域名；域名不变则小程序端零改动） |
| 服务 | FastAPI + uvicorn，`scripts/server.sh` 管理，端口 8000（仅内网） |
| 反向代理 | nginx + certbot（HTTPS） |
| 数据库 | SQLite WAL：`$BACKEND/mustdo.db` |
| 外部 API | 火山引擎极速版 ASR、DeepSeek |

## 一、新 VPS 部署

### 0. 数据抢救（任何操作之前）

- HK VPS 商家控制台查**快照/自动备份**能否恢复
- 本地若有旧生产库副本 → 拷到新机；没有 → 接受丢失，重新初始化
- ⚠️ 本地仓库的 `mustdo.db` 与 `.env` 是**测试数据**，不能当生产用

### 1. 基础环境

```bash
# 创建部署用户 todo（非 root 跑服务），SSH key 登录

# ── Debian/Ubuntu 系 ──
# apt update && apt install -y curl nginx certbot sqlite3

# ── AlmaLinux/CentOS/Rocky（RHEL 系，当前生产实测：AlmaLinux）──
sudo dnf install -y epel-release
sudo dnf install -y curl nginx certbot python3-certbot-nginx sqlite
# ffmpeg 无需系统安装：pyproject 的 imageio-ffmpeg 依赖在 uv sync 后自带静态 ffmpeg
# （Windows/macOS 微信客户端不支持 PCM 录音，上传的 mp3 等格式由它转码后再送 ASR）

# uv（两系通用，部署用户）
curl -LsSf https://astral.sh/uv/install.sh | sh

# rclone（两系通用，备份用）
curl https://rclone.org/install.sh | sudo bash
```

> 注意：RHEL 系 sqlite 包名是 `sqlite`（二进制仍是 `sqlite3`）；nginx 在 AppStream 仓库、certbot 在 EPEL。

### 2. 部署代码

```bash
git clone <仓库地址> /opt/mustdo && cd $BACKEND && uv sync
```

### 3. 配置 `.env`

参照 `backend/.env.example`，关键项：

- `SECRET_KEY`：**新生成**的随机值（勿用默认值）
- `VOLC_API_KEY`（新版认证优先）/ `VOLC_APP_KEY` + `VOLC_ACCESS_KEY`（旧版回退）
- `DEEPSEEK_API_KEY`
- 其余（`SESSION_DAYS`、`TIMEZONE=Asia/Shanghai`、`MAX_AUDIO_SECONDS`、`MIN_AUDIO_SECONDS`）用默认即可

### 4. 连通性预检（US VPS 特有）

火山/DeepSeek 是国内服务，从美国访问可能慢或不通，**先测通再继续**：

```bash
curl -sS -o /dev/null -w "deepseek: %{http_code}\n" https://api.deepseek.com
curl -sS -o /dev/null -w "volc: %{http_code}\n" https://openspeech.bytedance.com
```

### 5. 数据库

```bash
# 有旧库 → 直接放到 $BACKEND/mustdo.db
# 无旧库 → 初始化 + 生成邀请码：
cd $BACKEND && uv run python scripts/init_db.py
uv run python scripts/create_invite.py
```

### 6. 启动服务

```bash
scripts/server.sh start
curl -s http://127.0.0.1:8000/api/health   # 期望 {"status":"ok"}
```

### 7. DNS + HTTPS（顺序不能反）

1. DNS 面板把 `mustdo.doebkblcya.com` A 记录指到新 IP（提前调低 TTL）
2. `dig mustdo.doebkblcya.com` 确认生效
3. nginx server block：

```nginx
server {
    server_name mustdo.doebkblcya.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

4. `certbot --nginx -d mustdo.doebkblcya.com`（DNS 没生效签不了）

### 8. 端到端验证

- `curl https://mustdo.doebkblcya.com/api/health` → `{"status":"ok"}`
- 小程序真机：登录 + 语音新增一条（走完 ASR → DeepSeek → 入库）
- 微信公众平台：确认 request 合法域名仍是 `mustdo.doebkblcya.com`（域名没变就不用改）

## 二、定时备份（Cloudflare R2）

### 原理

- SQLite WAL 模式：运行中**不能直接 cp 数据库文件**（会漏掉 `-wal` 里未合并的提交）
- 脚本用 `sqlite3 .backup` 在线一致备份，服务运行中安全
- 备份内容 = 数据库 + `.env`（丢 `SECRET_KEY` 所有 session 作废）
- 保留期：本地 14 天 + R2 远端 90 天；**上传成功后才执行清理**，失败不删任何旧备份

### 1. R2 一次性配置（Cloudflare 控制台）

1. 建桶 `mustdo-backups`
2. R2 → Manage R2 API Tokens → 创建**仅授权该桶**的 Object Read & Write token（最小权限）

### 2. VPS 上配置 rclone

```bash
rclone config
# n → 名字 r2 → 类型 s3 → provider 选 Cloudflare →
# account id（R2 控制台可见）、access key、secret、endpoint https://<account_id>.r2.cloudflarestorage.com
# ⚠️ 域名是 cloudflarestorage.com，不是 cloudflared.com（后者是被停放的仿冒域名）
rclone mkdir r2:mustdo-backups
rclone lsd r2:   # 确认可见
```

### 3. 安装 cron（部署用户 `crontab -e`）

```cron
PATH=/usr/local/bin:/usr/bin:/bin:/home/todo/.local/bin
15 4 * * * /opt/mustdo/backend/scripts/backup.sh >> /opt/mustdo/backend/backups/cron.log 2>&1
16 4 * * * cd /opt/mustdo/backend && uv run python scripts/cleanup_overdue.py >> /opt/mustdo/backend/logs/cleanup.log 2>&1
@reboot sleep 5 && /opt/mustdo/backend/scripts/server.sh start
```

三行任务各司其职：每日备份上传、每日待办清理（软删超 7 天 + 未软删且截止日期超 7 天，含已完成项；`server.sh` 是 nohup 方案，重启不自起，用 `@reboot` 兜底）。

⚠️ cron 的 PATH 很精简：rclone/uv 路径必须可解析；`rclone.conf` 位于部署用户 HOME 下，cron 要以该用户身份运行。

### 4. 验证

```bash
scripts/backup.sh --local       # 只备份不上传，先验证脚本本身
scripts/backup.sh               # 完整跑一次
rclone lsl r2:mustdo-backups    # 确认远端有文件
tail backups/backup.log         # 看脚本日志
```

### 5. backup.sh 可覆盖的环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `DB_PATH` | `$BACKEND/mustdo.db` | 数据库路径 |
| `ENV_FILE` | `$BACKEND/.env` | .env 路径 |
| `BACKUP_DIR` | `$BACKEND/backups` | 本地备份目录 |
| `LOG_FILE` | `$BACKUP_DIR/backup.log` | 脚本日志 |
| `RCLONE_BIN` | `rclone` | rclone 可执行文件 |
| `R2_REMOTE` | `r2:mustdo-backups` | rclone remote:桶名 |
| `REMOTE_PATH` | 空 | 桶内子目录 |
| `KEEP_LOCAL_DAYS` | 14 | 本地保留天数 |
| `REMOTE_KEEP_DAYS` | 90 | 远端保留天数 |

## 三、灾难恢复

### 恢复步骤

```bash
# 1. 取最新备份（本地 backups/ 或 rclone copy r2:mustdo-backups /tmp/restore/）
mkdir -p /tmp/restore && tar xzf mustdo-backup-<时间戳>.tar.gz -C /tmp/restore

# 2. 校验（期望 ok）
sqlite3 /tmp/restore/mustdo.db "PRAGMA integrity_check"

# 3. 停服务、换库
cd $BACKEND && scripts/server.sh stop
cp /tmp/restore/mustdo.db $BACKEND/mustdo.db
cp /tmp/restore/.env $BACKEND/.env
scripts/server.sh start
```

### 月度演练

每月一次：把最新备份恢复到 `/tmp`，跑 `PRAGMA integrity_check` + 抽查几条查询（用户数、待办数），确认备份真的可用。别等下次炸机才发现备份是坏的。
