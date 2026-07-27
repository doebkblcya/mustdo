# Mustdo

一个轻量语音待办工具 — 按住说话，自动生成待办事项。

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

## 这是什么

说出来比打字快。Mustdo 让你按住按钮说出想做的事，AI 自动识别时间、日期并创建结构化待办。修改、完成、删除在界面上手动操作 — 语音只负责最快的那个动作：新增。

- **微信小程序** — 原生小程序，语音 + 手动管理待办
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
小程序录音 ──HTTP POST──▶ 火山引擎极速版 ASR ──▶ 转写文本
                                                │
                                         DeepSeek JSON 解析
                                                │
                                            SQLite 待办
```

小程序采集 16kHz/16bit/mono PCM 音频，松手后一次性 HTTP POST 到后端。后端封装 WAV header 后调用火山引擎录音文件极速版做识别，再调用 DeepSeek 做结构化解析。

## 快速开始

### 1. 后端

```bash
cd backend
cp .env.example .env          # 编辑 .env，填入火山引擎和 DeepSeek 的 API Key
uv sync
uv run python scripts/init_db.py
uv run python scripts/create_invite.py   # 生成注册邀请码
uv run uvicorn app.main:app --reload
```

服务器后台运行：

```bash
scripts/server.sh start        # stop | restart | status | logs
```

### 2. `.env` 必需配置

```bash
SECRET_KEY=change-me
VOLC_API_KEY=
DEEPSEEK_API_KEY=
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Pydantic |
| 数据库 | SQLite |
| 认证 | HttpOnly Cookie Session / Bearer Token |
| 语音识别 | 火山引擎录音文件极速版 |
| AI 解析 | DeepSeek Chat Completions (JSON Output) |
| 小程序 | 微信原生 + wx.request |

## 项目结构

```
.
├── backend/          FastAPI 后端
│   ├── app/
│   │   ├── routers/     认证、待办、语音
│   │   └── services/    火山 ASR、DeepSeek、待办逻辑
│   └── scripts/         数据库初始化、邀请码管理、过期清理
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
| `POST` | `/api/voice/transcriptions` | 上传音频转写 |
| `POST` | `/api/todos/ai` | 文本解析并新增待办 |

错误响应统一为 `{ code, message, details }` 结构。完整 API 文档见 [docs/PROJECT.md](docs/PROJECT.md)。

## 验证

```bash
python -m compileall backend/app backend/scripts backend/tests
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
```

## 参考

- [火山引擎录音文件极速版](https://docs.volcengine.com/docs/6561/1631584)
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)

## 许可

[MIT](LICENSE)
