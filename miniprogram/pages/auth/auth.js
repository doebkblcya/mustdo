const api = require("../../utils/api");

Page({
  data: {
    phase: "launching", // launching | invite | failed
    inviteTop: 96,
    inviteCode: "",
    error: "",
    submitting: false,
  },

  onLoad() {
    const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    const menuButton = wx.getMenuButtonBoundingClientRect ? wx.getMenuButtonBoundingClientRect() : null;
    this.setData({
      inviteTop: menuButton
        ? menuButton.bottom + 32
        : (windowInfo.statusBarHeight || 0) + 76,
    });
    this.silentLogin();
  },

  silentLogin() {
    this.setData({ phase: "launching", error: "" });
    api.wechatLogin()
      .then((result) => {
        if (result.needs_invite) {
          this.setData({ phase: "invite" });
        } else {
          wx.redirectTo({ url: "/pages/todos/todos" });
        }
      })
      .catch((err) => {
        this.setData({ phase: "failed", error: err.message || "微信登录失败，请重试" });
      });
  },

  retryLogin() {
    this.silentLogin();
  },

  onInviteInput(event) {
    this.setData({ inviteCode: event.detail.value, error: "" });
  },

  submitInvite() {
    if (this.data.submitting) return;
    const code = this.data.inviteCode.trim();
    if (!code) {
      this.setData({ error: "请输入邀请码" });
      return;
    }
    this.setData({ submitting: true, error: "" });
    api.redeemInvite(code)
      .then(() => {
        wx.redirectTo({ url: "/pages/todos/todos" });
      })
      .catch((err) => {
        this.setData({ submitting: false, error: err.message || "邀请码无效" });
      });
  },
});
