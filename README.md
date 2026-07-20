# Todo Analyzer

一个轻量语音待办工具 — 按住说话，自动生成待办事项。

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![TypeScript](https://img.shields.io/badge/typescript-5.x-3178c6.svg)](https://www.typescriptlang.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19.x-61dafb.svg)](https://react.dev/)

## 这是什么

说出来比打字快。Todo Analyzer 让你按住按钮说出想做的事，AI 自动识别时间、日期并创建结构化待办。修改、完成、删除在界面上手动操作 — 语音只负责最快的那个动作：新增。

- **Web Demo** — Vite + React SPA，第一客户端，验证完整链路
- **微信小程序** — 原生小程序，复用同一套后端 API
- **iOS 客户端** — 计划中

## 功能

- 按住说话，松手后自动语音转文字 → AI 解析 → 创建待办
- 流式转写，说话时看到实时识别结果
- 今天 / 明天 / 后续动态分类，时间线视图
- 无具体时间事项置顶，有具体时间事项按时间排列
- 支持自然语言日期：「周五」「下周三」「月底」
- 手动编辑内容、日期、时间、完成状态和删除
- 用户名/密码登录 + 单次邀请码注册，数据按用户隔离

## 语音链路

```
浏览器录音 ──WebSocket──▶ 讯飞语音听写 ──▶ 转写文本
                                            │
                                     DeepSeek JSON 解析
                                            │
                                        SQLite 待办
```

前端采集音频并下采样为 16kHz/16bit/mono PCM，通过 WebSocket 流式发送给后端。后端封装讯飞 ASR 协议、调用 DeepSeek 做结构化解析，前端不直连第三方服务。

## 快速开始

### 1. 后端

```bash
cd backend
cp .env.example .env          # 编辑 .env，填入讯飞和 DeepSeek 的 API Key
uv sync
uv run python scripts/init_db.py
uv run python scripts/create_invite.py   # 生成注册邀请码
uv run uvicorn app.main:app --reload
```

服务器后台运行：

```bash
scripts/server.sh start        # stop | restart | status | logs
```

### 2. 前端

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev                    # http://localhost:5173
```

Vite 自动代理 `/api` 到后端 `127.0.0.1:8000`。详细部署配置（自定义域名、CORS、HTTPS Cookie）见 [docs/PROJECT.md](docs/PROJECT.md)。

### 3. `.env` 必需配置

```bash
SECRET_KEY=change-me
IFLYTEK_APP_ID=
IFLYTEK_API_KEY=
IFLYTEK_API_SECRET=
DEEPSEEK_API_KEY=
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Pydantic |
| 数据库 | SQLite |
| 认证 | HttpOnly Cookie Session / Bearer Token |
| 语音识别 | 讯飞语音听写 WebAPI |
| AI 解析 | DeepSeek Chat Completions (JSON Output) |
| 前端 | Vite + React + TypeScript |
| 音频采集 | Web Audio API + PCM 下采样 |
| 小程序 | 微信原生 + wx.request + wx.connectSocket |

## 项目结构

```
.
├── backend/          FastAPI 后端
│   ├── app/
│   │   ├── routers/     认证、待办、语音
│   │   └── services/    讯飞 ASR、DeepSeek、语音编排、待办逻辑
│   └── scripts/         数据库初始化、邀请码管理、过期清理
├── frontend/         Vite + React 前端
│   └── src/
│       ├── voice/        录音、WebSocket、语音组件
│       ├── todos/        待办页面
│       └── auth/         登录注册
├── miniprogram/      微信小程序
└── docs/             架构与开发文档
```

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/register` | 注册 |
| `POST` | `/api/auth/login` | 登录 |
| `POST` | `/api/auth/token/register` | 注册（小程序 Bearer Token） |
| `POST` | `/api/auth/token/login` | 登录（小程序 Bearer Token） |
| `POST` | `/api/auth/logout` | 登出 |
| `GET` | `/api/me` | 当前用户 |
| `GET` | `/api/todos` | 获取待办（今天/明天/后续分组） |
| `PATCH` | `/api/todos/{id}` | 编辑待办 |
| `DELETE` | `/api/todos/{id}` | 删除待办 |
| `WS` | `/api/voice/stream` | 流式语音识别 |
| `POST` | `/api/todos/ai` | 文本解析并新增待办 |

错误响应统一为 `{ code, message, details }` 结构。完整 API 文档见 [docs/PROJECT.md](docs/PROJECT.md)。

## 验证

```bash
python -m compileall backend/app backend/scripts backend/tests
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
(cd frontend && npm run typecheck)
```

## 参考

- [讯飞语音听写 WebAPI](https://www.xfyun.cn/doc/asr/voicedictation/API.html)
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)

## 许可

[MIT](LICENSE)
