# Mustdo 微信小程序

微信小程序客户端，复用 FastAPI 后端。

## 配置

后端地址在 `config.js`：

```js
const API_BASE_URL = "https://mustdo.doebkblcya.com";
```

微信公众平台后台需要配置：

```text
request 合法域名：https://mustdo.doebkblcya.com
```

> 不再需要 socket 合法域名（语音改为 HTTP POST 上传，不再使用 WebSocket）。

## 认证

小程序使用 Bearer Token：

```text
POST /api/auth/token/login
POST /api/auth/token/register
Authorization: Bearer <token>
```

Token 存在小程序本地 storage 中，后端通过 `sessions` 表校验。

## API 一览

| 页面 | 接口 |
|------|------|
| 登录 | `POST /api/auth/token/login` |
| 注册 | `POST /api/auth/token/register` |
| 待办列表 | `GET /api/todos` |
| 完成/编辑 | `PATCH /api/todos/{id}` |
| 删除 | `DELETE /api/todos/{id}` |
| 语音转写 | `POST /api/voice/transcriptions`（`wx.uploadFile` 上传 PCM 文件） |
| AI 解析 | `POST /api/todos/ai` |

## 语音流程

```
按住 → 本地录音（16kHz/mono/PCM）→ 松手 → wx.uploadFile → 后端转写 → AI 解析 → 入库
```

不再使用 WebSocket 流式发送。录音参数见 `pages/todos/todos.js` 中 `recorder.start`。
