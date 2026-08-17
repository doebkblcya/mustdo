<div align="center">

# Mustdo

**轻量语音待办工具 — 按住说话，AI 自动识别时间，生成结构化待办**

> "说出来比打字快。"

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57.svg)](https://www.sqlite.org/)
[![WeChat Mini Program](https://img.shields.io/badge/WeChat-%E5%B0%8F%E7%A8%8B%E5%BA%8F-07C160.svg)](https://developers.weixin.qq.com/miniprogram/dev/framework/)

**微信小程序** · **FastAPI** · **SQLite** · **火山引擎 ASR** · **DeepSeek**

</div>

---

## 目录

- [这是什么](#这是什么)
- [核心原则](#核心原则)
- [功能特性](#功能特性)
- [语音使用流程](#语音使用流程)
- [语音 → 待办 数据流](#语音--待办-数据流)
- [自然语言日期](#自然语言日期)
- [快速开始](#快速开始)
- [技术栈](#技术栈)
- [API 摘要](#api-摘要)
- [项目结构](#项目结构)
- [路线图](#路线图)
- [常见问题](#常见问题)
- [验证与维护](#验证与维护)
- [参考](#参考)

---

## 这是什么

Mustdo 是一个**轻量语音待办工具**。你只需要按住按钮、说出想做的事，剩下的交给机器：语音转文字 → AI 识别日期和时间 → 自动创建结构化待办。

修改、完成、删除在界面上手动操作 —— 语音只负责最快的那个动作：**新增**。

## 核心原则

| 原则 | 说明 |
|------|------|
| **主流程要短** | 按住说话 → 松手 → 自动转写、解析、入库，没有中间确认 |
| **语音不做危险操作** | 不通过 AI 修改或删除已有事项，语音只负责新增 |
| **AI 结果不做确认弹窗** | 解析过程可见，失败不写入数据，不打扰用户 |
| **多端优先** | 微信小程序是第一客户端，后续 iOS 复用同一套后端 API |

## 功能特性

| 功能 | 说明 |
|------|------|
| **按住说话** | 16kHz/mono/PCM 录音，上限 60 秒；上滑取消，松手自动上传 |
| **文字输入** | 底部通栏切换文字模式，回车/发送键提交，与语音共用同一 AI 解析链路 |
| **AI 语音转写** | 火山引擎录音文件极速版，同步识别，一次请求即返回 |
| **智能解析** | DeepSeek JSON 输出，识别内容、日期、时间，支持自然语言日期 |
| **动态分类** | 今天 / 明天 / 后续 自动分组，过期自动隐藏并定期清理 |
| **置顶待办** | 右滑卡片切换置顶，暖色 accent 标识，列表内优先排序 |
| **左滑删除** | 左滑露出删除区，松手弹回 + 确认框，防误删 |
| **手动编辑** | 内容、日期、时间、完成状态均可在界面上手动修改 |
| **邀请码注册** | 单次 / 长期邀请码，数据按用户隔离 |
| **无障碍适配** | 跟随系统大字号，旧安卓设备自动降级动画 |

## 语音使用流程

```
① 按住说话  ──▶  ② 松手自动上传  ──▶  ③ 转写 + AI 解析  ──▶  ④ 待办入库
```

- **按住**：即时视觉反馈（按钮缩放 + 震动），无需等待
- **说话**：说出想做的事，比如「明天下午三点买菜」
- **松手**：一次性上传完整音频，进入「正在解析待办…」
- **完成**：待办出现在列表对应分组，无确认弹窗

> 提示：一条语音可以说多件事：「淘宝买螺丝还有双面胶，周五去超市买牛奶」会解析成两条待办。

**文字输入**：底部通栏默认按住说话，点右侧键盘图标切换到文字输入（自动聚焦），输入同样的自然语言（如「明天下午三点买菜」）即可，回车或点发送提交，与语音走同一条 AI 解析链路。

## 语音 → 待办 数据流

```text
┌────────────────┐  wx.uploadFile   ┌──────────────────┐
│    微信小程序     │ ───────────────▶ │     FastAPI 后端   │
│  按住说话录音     │     (PCM 文件)    │  PCM→WAV→base64   │
└────────────────┘                 └────────┬─────────┘
                                            │ HTTP POST
                                            ▼
                             ┌──────────────────────────┐
                             │   火山引擎 录音文件极速版    │
                             │  一次请求即返回，无需轮询     │
                             └────────────┬─────────────┘
                                          │ transcript
                                          ▼
                             ┌──────────────────────────┐
                             │     DeepSeek JSON 解析     │
                             │  动态日期 + few-shot 示例   │
                             └────────────┬─────────────┘
                                          │ 校验 content / due_date / due_time
                                          ▼
                             ┌──────────────────────────┐
                             │        SQLite 待办入库      │
                             └──────────────────────────┘
```

后端统一持有第三方 API key、prompt、音频格式处理和数据库写入逻辑。**前端不直连火山引擎或 DeepSeek**。

## 自然语言日期

AI 解析器内置上海时区的动态日期推理，今天是哪天由后端实时计算并注入 prompt：

| 你说 | 解析结果 |
|------|----------|
| 「明天下午三点买菜」 | `due_date=明天`，`due_time=15:00` |
| 「周五去超市买牛奶」 | 不早于今天的**最近一个周五** |
| 「下周五下午两点开会」 | **下一个自然周**的周五 |
| 「月底交房租」 | 当月最后一天 |
| 「后天」「大后天」 | 对应日期的动态计算 |
| 「有空把报告写完」 | 今天，无具体时间 |
| 「淘宝买螺丝还有双面胶」 | 同一场景合并为**一条**待办 |

规则：

- 没声明日期 → 默认为今天；过去日期 → 归正为今天
- 「上午 / 下午 / 晚上 / 早上」等模糊时段 → 不转成具体时间（`due_time=null`）
- 只声明了「下午三点」「15 点」这类明确时间 → 转 24 小时制 HH:MM
- 待办按 `置顶 → 未完成 → 无具体时间 → 时间升序 → id 升序` 排序

## 快速开始

### 1. 后端

```bash
cd backend
cp .env.example .env          # 编辑 .env，填入火山引擎和 DeepSeek 的 API Key
uv sync
uv run python scripts/init_db.py
uv run python scripts/create_invite.py               # 生成单次邀请码
uv run python scripts/create_invite.py --type multi   # 生成长期邀请码
uv run uvicorn app.main:app --reload
```

服务器后台运行：

```bash
cd backend
scripts/server.sh start        # stop | restart | status | logs
```

### 2. `.env` 必需配置

```bash
# 应用密钥，用于签名 session token 和邀请码 hash
SECRET_KEY=change-me-in-production

# 火山引擎语音识别（新版控制台只需 API Key）
VOLC_API_KEY=

# DeepSeek AI 解析
DEEPSEEK_API_KEY=
```

完整配置项（数据库路径、时区、登录态有效期、录音时长限制、DeepSeek 模型等）见 `backend/.env.example`。

### 3. 邀请码管理

```bash
cd backend
uv run python scripts/list_invites.py      # 查看邀请码记录
uv run python scripts/clear_invites.py     # 清空所有邀请码
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Pydantic v2 + uv |
| 数据库 | SQLite（WAL 模式，`check_same_thread=False`） |
| 认证 | Bearer Token（HMAC-SHA256）、pbkdf2_sha256 密码哈希 |
| 语音识别 | 火山引擎录音文件极速版（同步 HTTP POST，WAV base64） |
| AI 解析 | DeepSeek Chat Completions（JSON Output，thinking 禁用，temperature 0.1） |
| 小程序 | 微信原生框架（滑动交互 + 自定义 Spring 物理引擎） |

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/token/register` | 注册（需邀请码）并返回 Bearer Token |
| `POST` | `/api/auth/token/login` | 登录并返回 Bearer Token |
| `POST` | `/api/auth/logout` | 登出，撤销 Bearer Token |
| `GET` | `/api/me` | 当前用户 |
| `GET` | `/api/health` | 健康检查（无鉴权） |
| `GET` | `/api/todos` | 获取待办（今天/明天/后续分组） |
| `PATCH` | `/api/todos/{id}` | 编辑待办（内容/日期/时间/状态/置顶） |
| `DELETE` | `/api/todos/{id}` | 删除待办（软删除） |
| `POST` | `/api/voice/transcriptions` | 上传音频转写 |
| `POST` | `/api/todos/ai` | 文本解析并新增待办（支持多条，`source`: `voice`/`text`） |

错误响应统一为 `{ code, message, details }` 结构：`code` 是稳定机器码（供前端状态机和测试断言），`message` 是可直接展示的中文文案，`details` 为参数校验明细（无则为 `null`）。

## 项目结构

```
.
├── backend/                  FastAPI 后端
│   ├── app/
│   │   ├── main.py          应用入口、lifecycle
│   │   ├── config.py        配置加载（读取 .env）
│   │   ├── db.py            SQLite 连接 + schema 初始化与迁移
│   │   ├── deps.py          FastAPI 依赖（get_db、current_user）
│   │   ├── errors.py        统一错误处理
│   │   ├── schemas.py       Pydantic 请求/响应模型
│   │   ├── security.py      密码 hash、session token、邀请码
│   │   ├── time_utils.py    Asia/Shanghai 时间工具
│   │   ├── routers/         认证、待办、语音路由
│   │   └── services/        火山 ASR、DeepSeek、音频处理、待办逻辑
│   ├── scripts/             数据库初始化、邀请码管理、过期清理、server.sh
│   └── tests/               后端单元测试（5 个文件 20 个用例）
├── miniprogram/             微信小程序
│   ├── pages/auth/          登录 / 注册
│   ├── pages/todos/         待办列表和语音输入
│   └── utils/api.js         Bearer Token API client
└── docs/                    架构文档、ASR 方案分析、命名规范
```

## 路线图

**近期**

- 补齐待办分组 / 时间规则 / 编辑置顶交互的测试
- 管理员脚本：重置密码、禁用用户、撤销邀请码

**中期**

- iOS 客户端（复用同一套后端 API）
- 账号绑定设计，为多端同步做准备
- 任务搜索、过期查看和完成项折叠
- 语音链路优化：mp3 直传火山 ASR，跳过 ffmpeg 转码

**远期**

- 根据真实使用数据评估提醒功能
- 评估 SQLite → PostgreSQL 迁移
- 多 ASR/LLM 供应商切换、请求观测与延迟统计

## 常见问题

**为什么语音只能新增待办？**

安全优先。修改、删除、完成通过 AI 一句话完成的风险远高于收益，这些操作保留手动操作，避免误改误删。

**松手后要等多久？**

转写（一次 HTTP POST）+ AI 解析（JSON 输出）通常数秒完成，期间界面显示「正在解析待办…」。失败不写入数据，直接提示，不会让用户等一个不确定的结果。

**如何获得邀请码？**

后端管理员运行 `scripts/create_invite.py` 生成（单次 `TODO-S-...` 或长期 `TODO-M-...`）。邀请码只存 hash，明文仅生成时输出一次。

**数据存在哪里？**

每条待办属于登录用户，数据按用户隔离存储在后端 SQLite（WAL 模式）。语音音频转写后即弃，不落库。

## 验证与维护

```bash
# 语法编译检查
python -m compileall backend/app backend/scripts backend/tests

# 运行测试（认证 / 待办 / 语音 / DeepSeek / 错误模型）
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v

# 清理过期待办
cd backend && uv run python scripts/cleanup_overdue.py
```

## 参考

- [火山引擎录音文件极速版](https://docs.volcengine.com/docs/6561/1631584) — 协议细节见 `docs/极速版.md`
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- 详细架构文档：[docs/PROJECT.md](docs/PROJECT.md)
- ASR 选型决策记录：[docs/voice-asr-analysis.md](docs/voice-asr-analysis.md)
- AI 辅助开发约定：[CLAUDE.md](CLAUDE.md)

## 许可

[MIT](LICENSE)
