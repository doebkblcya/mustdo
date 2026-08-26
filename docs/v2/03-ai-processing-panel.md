# ASR 与 AI 统一处理面板

## 1. 目标

使用同一个面板展示语音识别、AI 解析和保存过程，让用户清楚看到系统正在处理什么以及最终创建了什么。

语音与文字输入复用同一套组件、同一套状态机与同一套后端接口；自动添加与添加前确认两种模式共享同一条处理管道，仅在"保存前是否停留"上分叉。

## 2. 范围

本版覆盖后端接口契约、用户交互逻辑与前端展示逻辑，视觉设计由 UI 稿另行定义。

## 3. 处理流程

```text
语音输入：录音 → 上传 → ASR 识别 → 展示转写 → AI 解析 → 展示结构化待办 → 保存
文字输入：展示输入文本 → AI 解析 → 展示结构化待办 → 保存
```

两条链路在"AI 解析"之后完全合并，统一为一条管道：

```text
POST /api/todos/parse  →  (确认模式：停留审核)  →  POST /api/todos/batch
```

展示数据（不含视觉样式）：

```text
转写：明天下午三点买菜，周五交房租
解析：[买菜(明天 15:00), 交房租(周五)]
保存：created = [id:12 买菜, id:13 交房租]
```

### 架构说明

- **解析与保存分离为两个端点**：确认模式需要在解析结果与保存之间插入用户审核（改转写、改条目、删条目），解析产物必须先以可编辑形态交给前端，再由前端按最终条目保存；
- **两种模式共用同一条管道**：自动模式 = parse 返回后自动发 batch；确认模式 = parse 返回后停留 reviewing，用户确认后发 batch。面板代码只有一条"解析→保存"流水线，差异只在中间是否停留；
- **自动模式保存失败后重试只重发 batch**：`items` 保持 parse 结果，避免重复 AI 解析。

## 4. 后端改动

### 4.1 接口总览

| 方法 | 路径 | 动作 | 说明 |
|------|------|------|------|
| POST | `/api/voice/transcriptions` | 复用 | 音频→ASR→文本 |
| POST | `/api/todos/parse` | 新增 | 文本→AI 解析，返回结构化条目，不写库 |
| POST | `/api/todos/batch` | 新增 | 按显式条目批量创建待办 |
| PATCH | `/api/todos/{id}` | 复用 | 编辑单条（列表编辑能力） |
| GET | `/api/todos` | 复用 | 保存后刷新列表 |

数据落于现有 `todos` 表；模式偏好存客户端（§5.3）。

### 4.2 `POST /api/todos/parse`

```python
class TodoParseRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    source: Literal["voice", "text"] = "voice"   # 日志区分输入来源

class ParsedItemOut(BaseModel):
    content: str
    due_date: date
    due_time: str | None

class TodoParseResponse(BaseModel):
    transcript: str
    items: list[ParsedItemOut]     # 解析结果，尚无 id，未写库
    message: str | None = None
```

- 200：解析成功；无新增待办时返回 200 + `items=[]` + `message`；
- 502 `todo_parse_unavailable`：解析服务不可用；
- 复用 `parse_todos_with_deepseek` 服务与既有归一化规则（日期归正、内容清洗、上限 20 条）；
- 本端点只解析，产物由前端持有，后续经 `/api/todos/batch` 保存。

### 4.3 `POST /api/todos/batch`

```python
class BatchCreateItem(BaseModel):
    content: str = Field(min_length=1, max_length=200)
    due_date: date
    due_time: str | None = None

class BatchCreateRequest(BaseModel):
    items: list[BatchCreateItem] = Field(min_length=1, max_length=20)

# 201 -> {"items": [TodoPublic]}
```

- 保存的条目可能经过用户编辑（reviewing 中修改过 content/due_date/due_time），后端按显式条目创建；
- 归一化与解析结果一致：content 折叠空白且非空；`due_time` 空串→`null`，否则必须 `HH:MM`；过去日期归正为今天；
- 事务：`BEGIN IMMEDIATE` 逐条 INSERT，整体成功或整体回滚（复用 `create_todos`）；
- 422 `validation_error`：参数非法；500 `todo_save_failed`：保存失败。

### 4.4 错误码与日志

错误码使用既有约定：

| 错误码 | HTTP | 触发点 |
|--------|------|--------|
| `validation_error` | 422 | parse/batch 参数校验 |
| `todo_parse_unavailable` | 502 | parse 解析服务失败 |
| `todo_save_failed` | 500 | batch 保存失败 |
| `recording_too_short` / `recording_too_long` / `audio_empty` / `audio_transcode_failed` / `unsupported_audio` | 400/415 | 上传链路（复用） |
| `speech_recognition_failed` | 502 | ASR 失败（复用） |
| `todo_not_found` | 404 | 列表编辑单条（复用） |

日志沿用现有事件风格：`todos_parse_done` / `todos_parse_failed`、`todos_batch_done` / `todos_batch_failed`，记录 elapsed_ms、transcript 长度、source、条目数。

## 5. 两种添加模式

### 5.1 模式定义

| 模式 | 默认 | 流程 | 保存前 |
|------|------|------|--------|
| 自动添加 | 是 | parse → 自动 batch | 不停留 |
| 添加前确认 | 否 | parse → reviewing → 用户确认 → batch | 停留，等待用户操作 |

两种模式共用同一条管道与面板状态机，区别仅在于 reviewing 是否停留。ASR 与 AI 解析在两种模式下都执行。

### 5.2 自动添加

- parse 返回后立即发起 batch，结构化结果在面板上展示后即进入保存；
- 保存成功进入 done，展示实际新增的每条待办，随后自动关闭并刷新列表；
- 全程无用户操作点，追求最短路径。

### 5.3 添加前确认

- parse 完成后停留在 reviewing，展示转写（或原文）与结构化条目；
- 用户可编辑转写后重新解析、编辑单条内容/日期/时间、删除某条、确认添加剩余条目；
- 确认后统一走 batch 保存；
- 模式偏好存客户端 `wx.setStorageSync(ADD_MODE_KEY, "auto" | "confirm")`，默认自动；设置页提供切换入口。

## 6. 面板状态机

### 6.1 状态定义

统一状态 `phase`，语音/文字共用：

| 状态 | 触发 | 面板持有数据 | 允许的操作 |
|------|------|--------------|-----------|
| `uploading` | 语音松手后上传（仅语音） | 本地 `tempFilePath` | 无（请求在途） |
| `transcribing` | ASR 请求中（仅语音） | `tempFilePath` | 无 |
| `parsing` | parse 请求中 | `transcript` | 无 |
| `reviewing` | 确认模式解析完成 | `transcript` + `items[]`（无 id，可编辑） | 编辑转写→重新解析；编辑/删除单条；确认添加；关闭（需确认） |
| `saving` | 确认模式确认后，batch 请求中 | `items[]` | 无 |
| `done` | 保存成功 | `created: TodoPublic[]` | 查看结果；关闭 |
| `error` | 任一步骤失败 | 失败点 + 已保留数据（§7.4） | 按失败点重试 / 重录 / 关闭 |

约束：

- 语音链路顺序 `uploading → transcribing → parsing → (reviewing | saving) → done / error`；文字链路跳过前两者；
- 自动模式在 `parsing` 后直接进入 `saving`（parse 返回即自动 batch），`reviewing` 仅确认模式出现；
- 每个状态保留已完成步骤的数据，错误恢复从当前阶段继续。

### 6.2 面板关闭规则

| 场景 | 行为 |
|------|------|
| `uploading`/`transcribing`/`parsing`/`saving`（请求在途） | 面板保持展开；页面卸载时请求继续执行，结果照常落库，用户可从列表查看 |
| `reviewing`（存在待审核结果） | 关闭需确认：丢弃本地 `transcript` + `items`，无后端动作 |
| `reviewing` 且 `items` 为空 | 直接关闭，无需确认（没有待审核结果） |
| `done` / `error` | 可随时关闭 |

## 7. 用户交互逻辑

### 7.1 自动添加（语音）

1. 松手 → `uploading`，面板出现；
2. `uploadVoice` 成功 → `transcribing`；失败 → `error(errorStep=uploading)`，提供重试（同一 `tempFilePath` 重传）；
3. 拿到转写 → `parsing`，面板展示转写；转写为空（静音）→ 提示重新录音；
4. parse 成功 → 展示结构化结果，随后自动发起 batch；
5. batch 成功 → `done`，展示 `created` 各条，自动关闭并 `loadTodos()`；
6. 任一步失败 → `error`，按 §7.4 恢复。

### 7.2 添加前确认（语音/文字同构）

1. 上传+ASR（语音）或直接提交（文字）→ `parsing`，请求 parse；
2. 成功 → `reviewing`，展示转写（或原文）+ 结构化 `items`；
3. 用户操作：
   - **确认添加** → `saving`，请求 batch（`items` 为面板中可能已编辑的最终列表）→ 成功 `done`，失败 `error(errorStep=saving)` 保留 `items` 重试；
   - **编辑转写/原文** → 重新解析（§7.3）；
   - **编辑单条** → 本地修改 content/due_date/due_time（日期选择器最早今天，时间可清空），确认时随批量保存；
   - **删除某条** → 本地移除；`items` 为空时确认按钮置灰；
   - **关闭** → 放弃确认（§6.2），结果停留在本地，未落库。

### 7.3 重新解析

`reviewing` 中编辑转写/原文后触发：再次请求 parse，用新返回的 `items` 整体替换面板中的旧条目（基于旧文本的本地编辑一并丢弃）。返回 `items=[]` 时面板展示 `message` 并清空条目，可继续编辑重试或关闭。

### 7.4 失败恢复矩阵

| 失败点 | 触发条件 | 已保留数据 | 用户操作 | 恢复动作 |
|--------|----------|-----------|----------|----------|
| 上传 | 网络失败 / `audio_empty` | `tempFilePath` | 重试 | 同一文件重传 |
| 上传 | `recording_too_short` / `recording_too_long` | — | 重新录音 | 回到录音，≤60s |
| 上传 | `unsupported_audio` / `audio_transcode_failed` | `tempFilePath` | 重新录音 | 回到录音 |
| ASR | `speech_recognition_failed` | `tempFilePath` | 重试 / 重录 | 重传或重录 |
| 静音 | 200 + `transcript=""` | — | 重录 / 重试 | 提示后回到录音 |
| 解析 | `todo_parse_unavailable` | `transcript` | 重试解析 | 重发 parse |
| 解析 | 200 + `items=[]` + message | `transcript` | 编辑原文重试 / 关闭 | 重新解析；关闭无需确认 |
| 保存 | `todo_save_failed` | `items`（当前面板列表） | 重试保存 | 重发 batch，`items` 保持 parse 结果 |

### 7.5 边界情况

- **401 鉴权过期**：面板内所有请求复用 `api.js` 既有约定——静默重登后重试一次，仍失败才报错；
- **重复提交**：`panel.phase` 处于 `uploading`/`transcribing`/`parsing`/`saving` 时，新的提交或录音入口被屏蔽；
- **页面卸载于请求在途**：请求继续执行，结果照常落库（§6.2）。

## 8. 前端展示逻辑

### 8.1 面板数据模型

单一面板组件，状态集中在一个 `panel` 对象（替换现有 `voicePhase`/`voiceMessage`/`transcript` 字段）：

```js
panel: {
  phase: "idle",               // idle|uploading|transcribing|parsing|reviewing|saving|done|error
  mode: "auto" | "confirm",    // 进入面板时从 storage 读取
  source: "voice" | "text",
  transcript: "",              // 转写或输入原文；parsing/reviewing 展示
  items: [],                   // parse 结果（无 id）；reviewing 中可编辑/删除
  created: [],                 // 已保存的 TodoPublic[]；done 展示
  message: "",                 // 无待办提示 / error 文案
  errorStep: "",               // uploading|transcribing|parsing|saving；error 态重试依据
  tempFilePath: "",            // 语音上传失败重试用
}
```

### 8.2 渲染规则（数据层面）

- **步骤序列按来源裁剪**：语音 = [上传, 识别, 解析, 保存]，文字 = [解析, 保存]；`uploading`/`transcribing` 在文字链路不渲染；
- **折叠语义**：已完成步骤折叠为单行摘要，保留其数据（识别步骤→转写摘录；解析步骤→条目数）；当前步骤展开；未开始步骤占位；
- **多结果滚动**：`items`/`created` 全部渲染，超过 4 条时面板内部滚动；
- **`done` 自动关闭**：保存成功后短暂停留并自动关闭；任一用户操作取消自动关闭计时；
- 面板只读 `panel` 状态渲染，展示数据不另存副本，保持单一数据源。

### 8.3 数据流

```text
语音：recorder.onStop → tempFilePath → uploading
      → uploadVoice() → transcript → transcribing
      → parseTodos(transcript, source=voice) → parsing → reviewing | saving
文字：submitComposerText → transcript → parsing
      → parseTodos(content, source=text) → reviewing | saving
确认保存：reviewing → batchCreateTodos(panel.items) → saving → done
自动保存：parse 返回后立即 batchCreateTodos(panel.items) → saving → done
```

`api.js` 接口：

- `parseTodos(transcript, source)` → `POST /api/todos/parse`；
- `batchCreateTodos(items)` → `POST /api/todos/batch`；
- `uploadVoice(filePath)` 不变。

### 8.4 列表刷新时机

| 时机 | 动作 |
|------|------|
| `done`（保存成功） | `loadTodos()` |
| 自动模式 `done` 自动关闭 | `loadTodos()` |
| `reviewing` 编辑/删除/重新解析 | 不刷新（未落库） |

### 8.5 组件职责划分

- `pages/todos/todos.js`：保留录音手势与输入框入口；`voicePhase` 相关分支替换为 `panel` 状态驱动；`composerSubmitting` 防重复提交保留；
- 面板逻辑独立为组件/模块（`panel` 数据模型 + 状态流转 + api 调用），语音与文字入口只负责把 `tempFilePath`/`transcript` 交给它；
- 录音参数（16k/mono/PCM、`RECORD_MAX_DURATION=60000`）与上传逻辑不变。

## 9. 验收标准

### 9.1 面板与流程

- 语音和文字使用同一套处理面板；
- 用户可以看见完整转写文本和结构化结果；
- 自动添加过程连续执行并显示中间步骤；
- 添加前确认会在保存前等待用户操作；
- 修改原文后可以重新触发 AI 解析；
- 任一步骤失败后已有结果得到保留，且可从面板内重试或重新录音。

### 9.2 后端

- parse 请求不产生任何 `todos` 行（可断言计数）；
- batch 任一条目非法 → 整体 422，无部分落库；成功返回带 id 的 `TodoPublic` 列表；
- 两个端点均有鉴权与统一错误格式 `{code, message, details}`。

### 9.3 交互与展示

- 请求在途（上传/识别/解析/保存）时面板保持展开；reviewing 关闭需确认，`items` 为空时不弹；
- 确认模式在用户确认前列表无任何变化；
- 自动模式保存成功展示实际新增的各条并自动关闭；
- 任一状态失败，均能在面板内完成重试/重录，且已完成步骤的数据可见。
