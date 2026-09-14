<div align="center">

# Mustdo

**按住说话，自动变成一条带日期和时间的待办**

微信小程序 · FastAPI · SQLite · 火山引擎 ASR · DeepSeek

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![WeChat Mini Program](https://img.shields.io/badge/WeChat-%E5%B0%8F%E7%A8%8B%E5%BA%8F-07C160.svg)](https://developers.weixin.qq.com/miniprogram/dev/framework/)

</div>

---

## 这是什么

Mustdo 是一个**语音待办工具**：按住按钮说出想做的事，松手，得到一条结构化待办。

> 「明天下午三点买菜」→ 语音转写 → 识别出内容、日期、时间 → 入库

全程不用打字，也不用去想「这是几号、几点」。

修改、完成、删除保留手动操作 —— 语音只负责最快的那个动作：**新增**。

## 系统架构

```text
┌────────────────┐   wx.uploadFile    ┌──────────────────────┐
│   微信小程序     │  ───────────────▶  │     FastAPI 后端      │
│  按住说话 · 录音  │       (MP3)        │ 鉴权 → 额度 → 时长校验 │
└────────────────┘                    └───────────┬──────────┘
                                                  │ 原始 MP3 直传
                                                  ▼
                                   ┌──────────────────────────┐
                                   │    火山引擎 ASR · 极速版    │
                                   │    同步接口，一次请求返回    │
                                   └─────────────┬────────────┘
                                                 │ transcript
                                                 ▼
                                   ┌──────────────────────────┐
                                   │    DeepSeek · JSON Output │
                                   │   动态日期 + few-shot 示例  │
                                   └─────────────┬────────────┘
                                                 │ 字段校验
                                                 ▼
                                   ┌──────────────────────────┐
                                   │      SQLite (WAL) 入库     │
                                   └──────────────────────────┘

任一环节失败 → 不写库，按统一错误模型返回
```

**客户端不直连第三方 AI 服务。** API key、prompt、音频格式处理、配额校验和入库逻辑全部收在后端，小程序只持有一个 Bearer Token。

## 功能概览

| 功能 | 说明 |
|---|---|
| **按住说话** | 16kHz/mono/48kbps MP3，上限 60 秒；上滑取消，松手自动上传 |
| **一句话多件事** | 「淘宝买螺丝还有双面胶，周五去超市买牛奶」解析为两条待办 |
| **自然语言日期** | 「明天下午三点」「周五」「下周五」「月底」由模型结合当前日期推理 |
| **文字输入** | 与语音共用同一条解析链路，仅跳过 ASR |
| **添加前确认** | 可选开关：先审核并编辑解析结果再保存，默认自动添加 |
| **动态分类** | 今天 / 明天 / 后续自动分组，过期项按规则自动清理 |
| **提醒** | 仅未完成且带具体时间的待办可设提醒，提醒时刻须落在 `(现在, 截止时刻]` |
| **置顶与删除** | 右滑置顶、左滑删除（弹回 + 确认防误删），乐观更新 + 失败回滚 |
| **AI 整理** | 对今日待办智能分组，结果本地缓存，集合未变则不发请求 |

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + Pydantic v2 + uv |
| 数据库 | SQLite（WAL 模式） |
| 认证 | 微信 `code` 换 OpenID + Bearer Token（HMAC-SHA256） |
| 语音识别 | 火山引擎录音文件极速版（同步 HTTP POST） |
| 语义解析 | DeepSeek Chat Completions（JSON Output，thinking 禁用） |
| 音频处理 | ffmpeg 解码校验时长；系统缺失时回退 imageio-ffmpeg 内置二进制 |
| 客户端 | 微信小程序原生框架（自定义 spring 物理引擎驱动滑动交互） |

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/wechat` | 微信静默登录；首次登录自动开户并分配默认额度 |
| `GET` | `/api/me` | 当前用户 |
| `GET` | `/api/me/quota` | 总额度、已用量与剩余量 |
| `GET` | `/api/health` | 健康检查（无鉴权） |
| `GET` | `/api/todos` | 待办列表（今天 / 明天 / 后续分组） |
| `PATCH` | `/api/todos/{id}` | 编辑（内容 / 日期 / 时间 / 状态 / 置顶） |
| `DELETE` | `/api/todos/{id}` | 软删除 |
| `PUT` | `/api/todos/{id}/reminder` | 设置或覆盖提醒 |
| `DELETE` | `/api/todos/{id}/reminder` | 取消提醒 |
| `POST` | `/api/voice/transcriptions` | 上传音频，返回转写文本 |
| `POST` | `/api/todos/parse` | 文本解析为结构化待办（不写库） |
| `POST` | `/api/todos/batch` | 批量新增待办 |

错误响应统一为 `{ code, message, details }`：`code` 是稳定机器码，`message` 可直接展示，`details` 为校验明细。

## 工程实践

**测试** —— 5 个测试文件、25 个用例，覆盖认证、待办接口、语音链路、解析服务与错误模型。每个用例使用临时 SQLite 并 patch 环境变量，不依赖外部服务。

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
```

**时间** —— 全链路统一 Asia/Shanghai，ISO 字符串存储。「今天 / 明天」由后端实时计算而非客户端传入，避免设备时区污染语义。

**数据边界** —— 语音音频仅用于当次转写，不落库；待办数据按用户隔离存储。

**清理** —— 每日脚本按「软删超 7 天」与「截止日期超 7 天」两条规则清理，含已完成项。

## 项目结构

```text
.
├── backend/
│   ├── app/
│   │   ├── routers/         认证、待办、语音
│   │   ├── services/        火山 ASR、DeepSeek、音频处理、待办逻辑
│   │   ├── db.py            SQLite 连接、schema 初始化与迁移
│   │   ├── errors.py        统一错误处理
│   │   ├── security.py      session token 生成与哈希
│   │   └── time_utils.py    Asia/Shanghai 时间工具
│   ├── scripts/             数据库初始化、过期清理、服务管理
│   └── tests/               单元测试
├── miniprogram/
│   ├── pages/               auth / todos / settings / trash
│   ├── components/          统一处理面板
│   ├── utils/api.js         Bearer Token API client
│   └── assets/icons/        Material Symbols 源文件 + 构建产物
└── docs/                    内部设计与运维记录
```

## 参考

- [火山引擎录音文件极速版](https://docs.volcengine.com/docs/6561/1631584)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)

## 许可

[MIT](LICENSE)
