# Rename: Todo Analyzer → Mustdo

本文档记录项目中所有需要从 "Todo Analyzer" / "todo-analyzer" / "todo_analyzer" 改为 "Mustdo" / "mustdo" 的位置，供后续迭代批量修改时参考。

## 命名约定

| 场景 | 旧名 | 新名 |
|------|------|------|
| 展示名 (Title Case) | `Todo Analyzer` | `Mustdo` |
| kebab-case | `todo-analyzer` | `mustdo` |
| snake_case | `todo_analyzer` | `mustdo` |
| 数据库文件 | `todo_analyzer.db` | `mustdo.db` |
| localStorage key | `todo_analyzer_token` / `todo_analyzer_user` | `mustdo_token` / `mustdo_user` |

---

## 低风险：文案/展示/文档

| # | 文件 | 行 | 当前内容 | 改为 |
|---|------|----|---------|------|
| 1 | `docs/PROJECT.md` | 3 | `本文档记录 Todo Analyzer 当前架构...` | `本文档记录 Mustdo 当前架构...` |
| 2 | `docs/PROJECT.md` | 7 | `Todo Analyzer 是一个轻量语音待办工具。...` | `Mustdo 是一个轻量语音待办工具。...` |
| 3 | `backend/app/__init__.py` | 1 | `"""Todo Analyzer backend package."""` | `"""Mustdo backend package."""` |
| 4 | `backend/app/main.py` | 24 | `title="Todo Analyzer"` | `title="Mustdo"` |
| 5 | `backend/pyproject.toml` | 4 | `description = "FastAPI backend for the Todo Analyzer MVP"` | `description = "FastAPI backend for Mustdo"` |
| 6 | `frontend/index.html` | 6 | `<title>Todo Analyzer</title>` | `<title>Mustdo</title>` |
| 7 | `frontend/src/auth/AuthPage.tsx` | 23 | `<h1>Todo Analyzer</h1>` | `<h1>Mustdo</h1>` |
| 8 | `frontend/src/todos/TodoDashboard.tsx` | 72 | `<h1>Todo Analyzer</h1>` | `<h1>Mustdo</h1>` |

## 中风险：包名/标识符

| # | 文件 | 行 | 当前内容 | 改为 | 备注 |
|---|------|----|---------|------|------|
| 9 | `backend/pyproject.toml` | 2 | `name = "todo-analyzer-backend"` | `name = "mustdo-backend"` | 修改后需 `uv lock --upgrade-package mustdo-backend` 更新 lock 文件 |
| 10 | `backend/uv.lock` | 375 | `name = "todo-analyzer-backend"` | `name = "mustdo-backend"` | 随 pyproject.toml 自动生成，或手动同步 |
| 11 | `frontend/package.json` | 2 | `"name": "todo-analyzer-frontend"` | `"name": "mustdo-frontend"` | |
| 12 | `frontend/package-lock.json` | 2, 8 | `"name": "todo-analyzer-frontend"` (2处) | `"name": "mustdo-frontend"` | `npm install` 后自动重写 |

## 高风险：有运行时影响

| # | 文件 | 行 | 当前内容 | 改为 | 影响与注意事项 |
|---|------|----|---------|------|---------------|
| 13 | `backend/app/config.py` | 71 | `database_path = Path(os.getenv("DATABASE_PATH", "./todo_analyzer.db"))` | 默认值改为 `"./mustdo.db"` | 仅影响未设置 `DATABASE_PATH` 环境变量的部署；修改后已有 DB 文件需重命名 |
| 14 | `backend/.env.example` | 2 | `DATABASE_PATH=./todo_analyzer.db` | `DATABASE_PATH=./mustdo.db` | 模板同步更新 |
| 15 | `backend/.env` | 2 | `DATABASE_PATH=./todo_analyzer.db` | `DATABASE_PATH=./mustdo.db` | 本地开发环境配置；修改后需将实际 `todo_analyzer.db` 文件重命名为 `mustdo.db` |
| 16 | `.gitignore` | 70 | `todo_analyzer.db` | `mustdo.db` | 确保新文件名不被提交 |
| 17 | `.gitignore` | 71 | `todo_analyzer.db-journal` | `mustdo.db-journal` | 确保 WAL 日志不被提交 |
| 18 | `miniprogram/utils/api.js` | 6 | `var TOKEN_KEY = "todo_analyzer_token";` | `var TOKEN_KEY = "mustdo_token";` | 所有已登录小程序用户的 localStorage token 失效，需重新登录 |
| 19 | `miniprogram/utils/api.js` | 7 | `var USER_KEY = "todo_analyzer_user";` | `var USER_KEY = "mustdo_user";` | 同上 |

---

## 修改执行建议

### 第一批：文案展示（可直接执行）
```
docs/PROJECT.md
backend/app/__init__.py
backend/app/main.py
backend/pyproject.toml (description only)
frontend/index.html
frontend/src/auth/AuthPage.tsx
frontend/src/todos/TodoDashboard.tsx
```

### 第二批：包名（修改后需验证构建）
```
backend/pyproject.toml (name)
frontend/package.json
```
修改后验证：
```bash
cd backend && uv lock       # 更新 uv.lock
cd frontend && npm install   # 更新 package-lock.json
```

### 第三批：运行时路径/key（需协调部署）
```
backend/app/config.py
backend/.env.example
backend/.env
.gitignore
miniprogram/utils/api.js
```

### 本地 DB 迁移
修改 `.env` 和 `config.py` 后，如果本地已有数据：
```bash
cd backend
mv todo_analyzer.db mustdo.db
```
