# Todo Analyzer

Todo Analyzer 是一个个人使用的小型 FastAPI 服务，用来把一段自然语言文本拆解成结构化 to-do list。

当前项目处于 MVP 阶段，核心目标是先把一个后端接口跑通：用户输入一段话，后端调用 mock 或真实大模型抽取待办事项，校验结构化结果，保存到 SQLite，然后返回标准化 JSON。

## 当前定位

这个项目暂时不是完整任务管理系统，也不是复杂 agent。当前更接近一个受控的 AI structured extraction workflow：

```text
一段自然语言文本
  -> AI 抽取 todo 业务字段
  -> Pydantic 校验
  -> 后端补全系统字段
  -> SQLite 保存
  -> API 返回结果
```

MVP 假设输入大多是一段短文本，而不是长会议纪要。因此当前实现采用同步接口和单次模型调用。

## 已实现功能

- FastAPI 后端应用。
- `GET /health` 健康检查接口。
- `POST /api/v1/analyses` 文本分析接口。
- Swagger UI 调试页面。
- ReDoc 文档页面。
- Pydantic 请求、响应、模型输出 schema。
- mock provider，本地调试时不消耗模型 token。
- OpenAI-compatible provider，可直接调用 OpenAI 官方或兼容 OpenAI `/chat/completions` 的第三方服务。
- `.env` 配置管理模型 API key、base URL、模型名、timeout、temperature、response format 等。
- SQLite 持久化。
- `analysis_runs` 表保存每次分析记录。
- `todos` 表保存拆解出的任务。
- `uv` 依赖管理。
- 中文设计文档和 MVP 实现计划。

## 尚未实现

- 前端 UI。
- 用户认证。
- API 自动化测试。
- 历史分析查询接口。
- 任务编辑、完成、归档接口。
- 长文本切分。
- 多模型自动 fallback。
- RAG 或历史任务去重。
- 日历、提醒、外部任务工具集成。
- `cost_usd` 成本计算。

## 技术栈

- Python 3.11
- FastAPI
- Pydantic
- Pydantic Settings
- SQLModel
- SQLite
- httpx
- uv

## 目录结构

```text
app/
  main.py
  api/
    v1/
      analyses.py
  core/
    config.py
    ids.py
  db/
    models.py
    persistence.py
    session.py
  schemas/
    analysis.py
  services/
    exceptions.py
    mock_provider.py
    openai_compatible_provider.py
    todo_analyzer.py
docs/
  api-design.md
  dependency-management.md
  mvp-implementation-plan.md
.env.example
.python-version
pyproject.toml
uv.lock
```

关键文件说明：

- [app/main.py](app/main.py)：FastAPI 应用入口，注册路由并在启动时初始化 SQLite 表。
- [app/api/v1/analyses.py](app/api/v1/analyses.py)：`POST /api/v1/analyses` 路由。
- [app/schemas/analysis.py](app/schemas/analysis.py)：接口请求、响应、模型输出结构。
- [app/services/todo_analyzer.py](app/services/todo_analyzer.py)：分析流程编排。
- [app/services/mock_provider.py](app/services/mock_provider.py)：本地 mock provider。
- [app/services/openai_compatible_provider.py](app/services/openai_compatible_provider.py)：真实模型调用 provider。
- [app/core/config.py](app/core/config.py)：从 `.env` 读取配置。
- [app/db/models.py](app/db/models.py)：SQLite 表模型。
- [app/db/persistence.py](app/db/persistence.py)：保存分析结果和 todo。

## 依赖管理

项目使用 `uv`，不维护 `requirements.txt`。

安装依赖：

```bash
uv sync
```

运行服务：

```bash
uv run uvicorn app.main:app --reload
```

运行测试：

```bash
uv run pytest
```

新增依赖：

```bash
uv add <package>
```

新增开发依赖：

```bash
uv add --dev <package>
```

## 启动项目

进入项目目录：

```bash
cd /home/songq1/code/internal-tools/todo-analyzer
```

安装依赖：

```bash
uv sync
```

复制配置文件：

```bash
cp .env.example .env
```

启动服务：

```bash
uv run uvicorn app.main:app --reload
```

服务启动后访问：

```text
http://127.0.0.1:8000
```

健康检查：

```text
http://127.0.0.1:8000/health
```

Swagger UI：

```text
http://127.0.0.1:8000/docs
```

ReDoc：

```text
http://127.0.0.1:8000/redoc
```

## 配置说明

配置文件模板是 [.env.example](.env.example)。

真实配置文件是 `.env`，它被 `.gitignore` 忽略，不应该提交。

### 数据库配置

```env
DATABASE_URL=sqlite:///./todo_analyzer.db
```

默认会在项目根目录生成 SQLite 数据库文件：

```text
todo_analyzer.db
```

该文件也被 `.gitignore` 忽略。

### Provider 配置

```env
AI_PROVIDER=mock
```

可选值：

```text
mock
openai_compatible
```

`mock` 表示使用本地 mock provider，不调用真实模型。

`openai_compatible` 表示调用真实大模型 API，当前实现走 OpenAI-compatible `/chat/completions` 协议。

### 真实模型配置

```env
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=
AI_MODEL_CHEAP=
AI_MODEL_BALANCED=
AI_MODEL_STRONG=
```

使用 OpenAI 官方时：

```env
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=
AI_MODEL_BALANCED=
```

使用第三方 OpenAI-compatible 网关时，把 `AI_BASE_URL` 和模型名改成服务商提供的值。

本地 `.env` 中需要填入真实 `AI_API_KEY` 和 `AI_MODEL_BALANCED`。不要把真实 `.env` 提交到 git。

当前接口支持三档模型：

```text
cheap
balanced
strong
```

MVP 阶段只配置 `AI_MODEL_BALANCED` 就可以。请求不传 `model_profile` 时，默认使用 `balanced`。

### 调用参数

```env
AI_REQUEST_TIMEOUT_SECONDS=30
AI_MAX_OUTPUT_TOKENS=1200
AI_TEMPERATURE=0.1
AI_RESPONSE_FORMAT=json_schema
AI_PROMPT_CACHE_KEY=
```

`AI_REQUEST_TIMEOUT_SECONDS`：模型请求超时时间，单位秒。

`AI_MAX_OUTPUT_TOKENS`：模型最多输出 token 数。

`AI_TEMPERATURE`：模型随机性。信息抽取任务建议保持低值，例如 `0` 或 `0.1`。

`AI_RESPONSE_FORMAT`：控制结构化输出方式。

可选值：

```text
json_schema
json_object
none
```

区别：

- `json_schema`：最严格，要求模型按我们定义的 schema 返回。OpenAI 官方或明确支持 structured output 的 provider 优先使用。
- `json_object`：只要求模型返回合法 JSON，不强制字段 schema。第三方网关兼容性通常更好。
- `none`：不传结构化输出参数，兼容性最高，但输出稳定性最低。

建议调试顺序：

```text
第三方网关先试 json_object
跑通后再试 json_schema
如果 provider 不支持这些参数，再改成 none
```

`AI_PROMPT_CACHE_KEY`：可选。默认留空，因为部分第三方网关会拒绝未知参数。接 OpenAI 官方并确认支持时可以设置固定值。

## 接口设计

核心接口：

```http
POST /api/v1/analyses
```

请求示例：

```json
{
  "content": "今天下午和产品开会确认登录页方案，明天让小王整理竞品截图。",
  "language": "zh-CN",
  "timezone": "Asia/Shanghai",
  "model_profile": "balanced",
  "options": {
    "default_category": "uncategorized"
  }
}
```

字段说明：

- `content`：必填，用户输入文本。
- `language`：输出语言，默认 `zh-CN`。
- `timezone`：用于解析“今天”“明天”“周五下午三点”等相对时间。
- `model_profile`：模型档位，支持 `cheap`、`balanced`、`strong`。
- `options.default_category`：模型无法判断分类时使用的默认分类。

响应示例：

```json
{
  "analysis_id": "0b6c1e6c7e224cfd88d19e2f6d99e89b",
  "status": "completed",
  "model": {
    "provider": "mock",
    "name": "mock-v0",
    "profile": "balanced"
  },
  "summary": {
    "todo_count": 1,
    "high_priority_count": 1,
    "detected_language": "zh-CN"
  },
  "todos": [
    {
      "id": "0c2cebf7dbf944e8be48d3a85d4fb1de",
      "title": "今天下午和产品开会确认登录页方案，明天让小王整理竞品截图",
      "description": "今天下午和产品开会确认登录页方案，明天让小王整理竞品截图",
      "category": "research",
      "priority": "high",
      "status": "open",
      "assignee": "小王",
      "due_at": "2026-06-04T23:59:59+08:00"
    }
  ],
  "usage": {
    "input_tokens": null,
    "output_tokens": null,
    "cost_usd": null,
    "latency_ms": 1
  },
  "created_at": "2026-06-03T10:20:30+08:00"
}
```

## 字段分工

大模型只负责生成需要语义理解的字段：

```text
title
description
category
priority
assignee
due_at
```

后端负责生成确定性字段：

```text
analysis_id
todo.id
todo.status
summary
usage
created_at
```

这样做的原因：

- 减少模型输出 token。
- 避免模型生成系统元数据。
- 降低返回结构漂移风险。
- 方便后端统一保存和统计。

## 分类和优先级

分类枚举：

```text
work
personal
learning
research
technical
communication
follow_up
uncategorized
```

优先级枚举：

```text
low
medium
high
```

任务状态枚举：

```text
open
completed
archived
```

分析接口生成的新任务默认都是 `open`。

## SQLite 持久化

当前数据库文件：

```text
todo_analyzer.db
```

当前表：

```text
analysis_runs
todos
```

`analysis_runs` 保存：

```text
id
content
language
timezone
model_profile
provider
model_name
status
input_tokens
output_tokens
cost_usd
latency_ms
created_at
```

`todos` 保存：

```text
id
analysis_id
title
description
category
priority
status
assignee
due_at
created_at
updated_at
```

MVP 阶段应用启动时会自动创建表，暂时不引入 Alembic migration。

## 调用真实大模型的流程

当 `AI_PROVIDER=openai_compatible` 时，后端流程是：

```text
POST /api/v1/analyses
  -> TodoAnalyzer
  -> OpenAICompatibleProvider
  -> httpx.AsyncClient
  -> AI_BASE_URL/chat/completions
  -> 解析模型返回 JSON
  -> Pydantic 校验
  -> 保存 SQLite
  -> 返回标准响应
```

当前不需要单独启动模型网关服务。只要模型服务提供 OpenAI-compatible API，FastAPI 后端会直接用 HTTP 调用它。

## 错误处理

当前接口会把 provider 相关错误转换成 HTTP 错误：

- `provider_not_configured`：配置缺失，例如没有配置 API key 或模型名。
- `model_failed`：模型服务请求失败，例如 HTTP 错误、超时、网络失败。
- `invalid_model_output`：模型返回内容不是合法 JSON，或无法通过 todo schema 校验。

## 本地调试建议

第一步先用 mock 模式确认接口和 SQLite 正常：

```env
AI_PROVIDER=mock
```

启动服务后打开：

```text
http://127.0.0.1:8000/docs
```

在 Swagger 里调用 `POST /api/v1/analyses`。

确认 mock 模式没问题后，再切到真实模型：

```env
AI_PROVIDER=openai_compatible
AI_RESPONSE_FORMAT=json_object
```

第三方网关跑通后，再尝试：

```env
AI_RESPONSE_FORMAT=json_schema
```

## 安全和提交注意事项

不要提交：

```text
.env
.venv/
todo_analyzer.db
__pycache__/
```

这些已经在 `.gitignore` 中配置。

可以提交：

```text
.env.example
.python-version
pyproject.toml
uv.lock
README.md
app/
docs/
```

`.env.example` 只能放空值或占位符，不能放真实 API key。

## 当前提交前检查

建议提交前运行：

```bash
git status --short --ignored
git ls-files --others --exclude-standard
```

确认 `.env`、`.venv/`、`todo_analyzer.db` 只出现在 ignored 列表中。

也可以做一次基础语法检查：

```bash
python -m compileall app
```

或者在 uv 环境中运行：

```bash
uv run python -m compileall app
```

## 后续计划

建议下一步按这个顺序推进：

1. 增加 API 自动化测试，固定当前 mock-backed endpoint 行为。
2. 用真实 API key 在 Swagger 中验证 `openai_compatible` provider。
3. 根据真实模型输出效果调整 prompt 和 schema。
4. 增加 `GET /api/v1/analyses/{analysis_id}` 查询接口。
5. 增加任务编辑、完成、归档接口。
6. 再开始做前端 UI。
