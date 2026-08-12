#!/usr/bin/env bash
# 每日备份：SQLite 在线一致备份 + .env → tar.gz → rclone 上传 Cloudflare R2 → 保留期清理
#
# 用法:
#   scripts/backup.sh           # 备份 + 上传 R2
#   scripts/backup.sh --local   # 只做本地备份，不上传（测试用）
#
# 关键点：数据库是 WAL 模式，直接 cp 文件会漏掉未合并的提交。
# 必须用 sqlite3 在线备份（.backup），服务运行中可安全执行。
# 保留期清理永远发生在上传成功之后——上传失败则不删任何旧备份。
#
# 环境变量覆盖（均有默认值，见 docs/DEPLOY.md）:
#   DB_PATH          数据库路径，默认 $BACKEND/mustdo.db
#   ENV_FILE         .env 路径
#   BACKUP_DIR       本地备份目录
#   LOG_FILE         脚本日志
#   RCLONE_BIN       rclone 可执行文件
#   R2_REMOTE        rclone remote:桶名，默认 r2:mustdo-backups
#   REMOTE_PATH      桶内子目录（可空 = 桶根）
#   KEEP_LOCAL_DAYS  本地保留天数（默认 14）
#   REMOTE_KEEP_DAYS 远端保留天数（默认 90）
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DB_PATH="${DB_PATH:-${BACKEND_DIR}/mustdo.db}"
ENV_FILE="${ENV_FILE:-${BACKEND_DIR}/.env}"
BACKUP_DIR="${BACKUP_DIR:-${BACKEND_DIR}/backups}"
LOG_FILE="${LOG_FILE:-${BACKUP_DIR}/backup.log}"

RCLONE_BIN="${RCLONE_BIN:-rclone}"
R2_REMOTE="${R2_REMOTE:-r2:mustdo-backups}"
REMOTE_PATH="${REMOTE_PATH:-}"

KEEP_LOCAL_DAYS="${KEEP_LOCAL_DAYS:-14}"
REMOTE_KEEP_DAYS="${REMOTE_KEEP_DAYS:-90}"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG_FILE"; }
fail() { log "ERROR: $*"; exit 1; }

# 目录必须最先就位——log/fail 都可能写日志，晚建就写不进去
mkdir -p "$BACKUP_DIR"

case "${1:-}" in
  --local) UPLOAD=false ;;
  "")      UPLOAD=true  ;;
  *)       echo "用法: $0 [--local]" >&2; exit 2 ;;
esac

command -v sqlite3 >/dev/null 2>&1 || fail "sqlite3 未安装（apt install sqlite3）"
if $UPLOAD; then
  command -v "$RCLONE_BIN" >/dev/null 2>&1 || fail "rclone 未安装（见 docs/DEPLOY.md）"
fi
[[ -f "$DB_PATH" ]] || fail "数据库不存在: $DB_PATH"
if [[ ! -f "$ENV_FILE" ]]; then
  log "WARN: .env 不存在: $ENV_FILE（备份将只有数据库）"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

log "开始备份: db=${DB_PATH}"

# 1. SQLite 在线一致备份（WAL 安全）
sqlite3 "$DB_PATH" ".backup '${WORKDIR}/mustdo.db'" || fail "sqlite3 .backup 失败"

# 2. 打包：数据库 + .env（丢了 SECRET_KEY 所有 session 作废）
cp "$ENV_FILE" "$WORKDIR/.env" 2>/dev/null || true
FILES=("mustdo.db")
[[ -f "$WORKDIR/.env" ]] && FILES+=(".env")
ARCHIVE="${BACKUP_DIR}/mustdo-backup-${STAMP}.tar.gz"
tar -czf "$ARCHIVE" -C "$WORKDIR" "${FILES[@]}" || fail "打包失败"
log "本地备份完成: $(basename "$ARCHIVE") ($(du -h "$ARCHIVE" | cut -f1))"

# 3. 上传 R2 + 远端大小校验 + 远端保留期清理
if $UPLOAD; then
  DEST="$R2_REMOTE"
  [[ -n "$REMOTE_PATH" ]] && DEST="$R2_REMOTE/$REMOTE_PATH"
  "$RCLONE_BIN" copy "$ARCHIVE" "$DEST/" >> "$LOG_FILE" 2>&1 || fail "rclone 上传失败"

  local_size="$(stat -c %s "$ARCHIVE")"
  remote_size="$("$RCLONE_BIN" lsl "$DEST/" 2>/dev/null | awk -v f="$(basename "$ARCHIVE")" '$4 ~ (f "$") {print $1}')"
  [[ "$remote_size" == "$local_size" ]] || fail "上传校验失败: 远端大小 ${remote_size:-缺失} ≠ 本地 ${local_size}"

  "$RCLONE_BIN" delete "$DEST" --min-age "${REMOTE_KEEP_DAYS}d" >> "$LOG_FILE" 2>&1 \
    || log "WARN: 远端过期清理失败（不影响本次备份）"
  log "R2 上传完成: ${DEST}/$(basename "$ARCHIVE")"
fi

# 4. 本地保留期清理（只匹配备份命名，严格大于 KEEP_LOCAL_DAYS 天）
find "$BACKUP_DIR" -maxdepth 1 -name 'mustdo-backup-*.tar.gz' -mtime "+${KEEP_LOCAL_DAYS}" -delete

log "备份完成"
