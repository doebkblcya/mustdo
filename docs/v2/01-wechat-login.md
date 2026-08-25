# 微信静默登录

## 目标

用户打开小程序后自动完成身份识别并进入待办页面，使用微信身份承载 Mustdo 用户体系。

## 用户流程

1. 小程序启动时调用 `wx.login` 获取临时 `code`。
2. 小程序将 `code` 提交给 Mustdo 后端。
3. 后端调用微信 `code2Session` 接口换取 `openid`。
4. 后端按 `openid` 查找用户；首次登录时自动创建用户。
5. 后端签发 Mustdo Bearer Token，并返回用户信息。
6. 小程序保存 Token，进入待办页面并加载数据。

整个过程通过启动状态展示进度，无需用户填写用户名、密码或邀请码。

## 数据设计

用户以 `wechat_openid` 作为微信小程序内的唯一身份标识：

```sql
users (
    id INTEGER PRIMARY KEY,
    wechat_openid TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
)
```

Session 继续使用随机 Bearer Token。数据库保存 Token 的 HMAC hash，并沿用有效期、撤销和启动清理机制。

## 后端接口

```http
POST /api/auth/wechat
Content-Type: application/json

{
  "code": "wx.login 返回的临时 code"
}
```

响应：

```json
{
  "user": {
    "id": 1
  },
  "token": "mustdo-session-token",
  "token_type": "bearer"
}
```

后端增加以下配置：

```env
WECHAT_APP_ID=
WECHAT_APP_SECRET=
```

## 异常处理

- `wx.login` 失败：保留启动页并提供重试按钮。
- `code2Session` 失败：显示“微信登录失败，请重试”。
- Session 失效：清除本地 Token，重新执行微信登录流程。
- 用户状态被禁用：显示账号当前不可用的稳定错误提示。

## 验收标准

- 首次打开小程序可以自动创建用户并进入待办页。
- 再次打开时识别为同一用户并读取原有待办。
- Session 失效后可以自动重新登录。
- 不同微信用户的数据相互隔离。
- 微信接口异常时可以在当前页面重试。

