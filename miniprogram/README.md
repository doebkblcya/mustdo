# mustdo Mini Program

微信小程序客户端复用同一套 FastAPI 后端。

## 配置

后端地址在 `config.js`：

```js
const API_BASE_URL = "https://doebkblcya.com";
```

微信公众平台后台需要配置：

```text
request 合法域名：https://doebkblcya.com
socket 合法域名：wss://doebkblcya.com
```

## 认证

小程序使用 Bearer Token，不依赖浏览器 Cookie：

```text
POST /api/auth/token/login
POST /api/auth/token/register
Authorization: Bearer <token>
```

Token 存在小程序本地 storage 中。后端仍复用 `sessions` 表，Web Demo 的 Cookie session 不受影响。

## 当前范围

- 登录 / 注册
- 今天 / 明天 / 后续待办列表
- 完成 / 修改 / 删除
- 按住说话，走 `wss://doebkblcya.com/api/voice/stream`

小程序录音目前按 `16kHz/mono/PCM` 发送给后端。真机调试时如发现微信录音格式兼容问题，优先调整 `pages/todos/todos.js` 中 `recorder.start` 的录音参数。
