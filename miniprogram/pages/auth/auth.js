const api = require("../../utils/api");

Page({
  data: {
    phase: "launching", // launching | failed
    error: "",
  },

  onLoad() {
    const storedUser = api.getStoredUser();
    if (api.getToken() && storedUser) {
      wx.redirectTo({ url: "/pages/todos/todos" });
      return;
    }
    this.silentLogin();
  },

  silentLogin() {
    this.setData({ phase: "launching", error: "" });
    api.wechatLogin()
      .then(() => {
        wx.redirectTo({ url: "/pages/todos/todos" });
      })
      .catch((err) => {
        this.setData({ phase: "failed", error: err.message || "微信登录失败，请重试" });
      });
  },

  retryLogin() {
    this.silentLogin();
  },
});
