# 语音转文字——ASR 选型与交互分析

> 记录小程序语音转文字功能在 ASR API 选型、EOS 调参、交互延迟等议题上的讨论过程和最终决策。

> **状态：历史决策记录。** 本文描述的讯飞 IAT 流式方案已下线并被替换。当前实现为**火山引擎录音文件极速版**（同步 HTTP POST，无 EOS 问题），代码在 `backend/app/services/asr.py`，协议见 `docs/极速版.md`。文中"按下延迟"的修复结论（视觉反馈移到异步操作之前）仍适用。

## 1. 产品需求

- 按住说话，松手结束（明确的开始/结束边界）
- 音频 ≤10s
- 快速响应，体感无延迟
- 上滑取消
- **不需要**录音过程中的实时转写（partial transcript）

## 2. 当前实现：讯飞 IAT 流式 WebSocket API

### 2.1 协议特征

| 特性 | 说明 |
|------|------|
| 协议 | WebSocket `wss://iat-api.xfyun.cn/v2/iat` |
| 鉴权 | HMAC-SHA256 签名 + base64（每次连接重新签名） |
| 音频格式 | 16kHz/16bit/mono PCM，每帧 1280B/40ms |
| 生命周期 | 连接 → 首帧(含参数) → 音频帧 → 结束帧(status=2) → 等待 final → 返回 |
| **EOS** | **End of Silence，后端点检测静默时长，默认 2000ms，无法关闭** |

### 2.2 架构

```
小程序 ─WS──→ 后端(FastAPI) ─WS──→ 讯飞 IAT
  wx.connectSocket    voice_stream.py      iflytek.py
                      transcribe_pcm_stream  IflytekIatClient
```

三层 WebSocket 链，后端作为代理：接收小程序 PCM 帧 → 拆分为 1280B 讯飞帧 → 发送给讯飞 → 返回 transcript。

## 3. EOS 问题

### 3.1 什么是 EOS

End of Silence。讯飞收到音频流后，通过 VAD（Voice Activity Detection）检测静音。连续静音超过 EOS 时长，判定"说完了"，返回 final 结果。

### 3.2 为什么你的场景不需要

你的场景有明确的开始/结束信号（按住/松手），不需要静音检测来判断"说完了没有"。但讯飞协议**强制要求 EOS 参数，无法设为 0**。

### 3.3 EOS 调参过程

| 阶段 | 值 | 结果 | 原因 |
|------|-----|------|------|
| 初始 | 3000ms（默认） | 松手后等 3.5s，太慢 | 等待太久 |
| 第一次调优 | 300ms | 短音频频繁报错"录音过短""未返回有效文本" | 用户按下后有沉默间隔（组织语言），EOS 在开口前就判停 |
| 最终 | **1500ms** | 平衡 | 容忍正常说话节奏，松手后 ~2s 返回 |

### 3.4 EOS 仅影响松手后延迟

```
按下 → 本地录音 → 说话 → 松手 → [EOS 等待] → 返回文本
 ↑                            ↑        ↑
 纯客户端                     客户端   仅这一段
 与 EOS 无关                          与 EOS 有关
```

松手后的延迟（~2s）可与 AI 解析延迟合并到 UI 提示中（"正在解析待办…"），对用户不敏感。

## 4. 按下的延迟——真正的痛点

### 4.1 问题诊断

初始代码中 `startVoice()` 的时序：

```javascript
async startVoice() {
    // 触摸坐标捕获

    await ensureRecordPermission();  // ← 阻塞 100-300ms

    setData({ voicePhase: "recording" });    // ← UI 才更新
    _animateVoiceButton(0.97);               // ← 按钮缩放
    wx.vibrateShort({ type: "heavy" });      // ← 震动

    recorder.start();  // ← onStart 才调 _animateVoicePanel
}
```

所有视觉反馈（按钮变色、动画、震动）都在异步权限检查之后，导致按下后有 **100-300ms 无响应窗口**。非首次使用时权限检查几乎瞬间，但仍有一次不必要的 await 阻塞。

### 4.2 修复

将视觉反馈移到所有异步操作之前：

```javascript
async startVoice() {
    // ── 即时视觉反馈（同步，~16ms 一帧）──
    resetVoiceState();
    setData({ voicePhase: "recording", ... });
    _animateVoiceButton(0.97);
    _animateVoicePanel(true);
    wx.vibrateShort({ type: "heavy" });

    // ── 异步操作（后台执行，不阻塞 UI）──
    await ensureRecordPermission();
    connectSocket();
    recorder.start();
}
```

**这是代码问题，不是 ASR 选型问题。**

## 5. ASR API 选型讨论

### 5.1 两个候选

| | 讯飞 IAT（当前） | HTTP POST 录音文件识别 |
|---|---|---|
| 协议 | WebSocket 流式 | HTTP POST |
| 传输方式 | 边录边发 | 录完一次性上传 |
| EOS | **必须，无法关闭** | **不存在** |
| 实时 partial | 支持 | 不支持 |
| 后端复杂度 | 高（分帧、签名、连接管理） | 低（POST 文件等结果） |
| 适合场景 | 会议记录、直播字幕 | **按住说话、语音搜索** |

### 5.2 为什么不需要实时流式

- 录音 ≤10s，全部录完再上传的延迟可接受
- 不需要录音过程中的逐字转写展示
- HTTP POST 不存在 EOS 问题
- 后端代码量从 ~500 行（voice_stream.py + iflytek.py）降到 ~50 行

### 5.3 为什么暂时保留当前方案（历史）

- 讯飞 IAT **可用**（EOS=1500ms 后工作正常）
- 按下延迟已修复（代码层面，与 API 无关）
- 松手后延迟 ~2s，可合并到解析 UI 中，不敏感
- 换 API 需要后端重写 + 云端账号开通，有一定成本

### 5.4 迁移结果：火山引擎录音文件极速版 ✅

后续按此方向完成了迁移，当前实现为火山引擎极速版（`backend/app/services/asr.py`）：

- 协议为同步 HTTP POST 一句话识别，无 EOS 问题
- 后端代码量从 ~500 行（voice_stream.py + iflytek.py）降到 ~150 行（asr.py + audio.py）
- 小程序仍是"录完一次性上传"，交互保持不变
- 配套：录音时长下限/上限校验、非 PCM 格式 ffmpeg 转码、新旧版控制台认证兼容

协议形态：

```
POST /recognize
Content-Type: application/octet-stream (或 base64 JSON)
Body: 完整 PCM 音频

Response: { "text": "识别结果" }
```

## 6. 结论

| 问题 | 根因 | 解决方案 | 状态 |
|------|------|----------|:---:|
| 按下后无反馈 | 代码把 UI 放在了 await 之后 | 视觉反馈移到异步之前 | ✅ |
| 松手后等太久 | EOS=3000ms | 降至 1500ms | ✅（已随讯飞方案下线） |
| 短音频误判"录音过短" | EOS=300ms 太激进 | EOS=1500ms | ✅（已随讯飞方案下线） |
| API 选型错误 | IAT 为流式场景设计 | 暂用 IAT，未来考虑 HTTP POST | ✅ 已迁移火山极速版 |
| 最后帧在 end 后到达 | recorder.onStop 与 onFrameRecorded 竞态 | setTimeout 150ms 延迟发 end | ✅（已随讯飞方案下线） |

## 7. 相关文件

### 文中提到的讯飞方案文件（均已删除）

| 文件 | 职责 |
|------|------|
| `backend/app/services/voice_stream.py` | ~~讯飞连接编排 + 识别事件处理~~（已删除） |
| `backend/app/services/iflytek.py` | ~~讯飞协议：鉴权 URL、音频帧、结束帧、解析响应~~（已删除） |
| `backend/app/config.py` | ~~EOS 配置 (`IFLYTEK_EOS_MS`)~~（已删除） |

### 当前实现（火山极速版）

| 文件 | 职责 |
|------|------|
| `miniprogram/pages/todos/todos.js` | 小程序端录音 + `wx.uploadFile` 上传 + 状态机 + UI |
| `backend/app/routers/voice.py` | HTTP 端点：转写 + AI 新增待办，认证和错误边界 |
| `backend/app/services/asr.py` | PCM→WAV→base64→火山极速版 HTTP 请求、文本提取 |
| `backend/app/services/audio.py` | 上传音频读取、时长校验、ffmpeg 转码 |
| `backend/app/services/deepseek.py` | DeepSeek JSON 解析和校验 |
