const api = require("../../utils/api");

Page({
  data: {
    mode: "login",
    username: "",
    password: "",
    inviteCode: "",
    error: "",
    submitting: false,
  },

  onLoad() {
    if (api.getToken()) {
      wx.redirectTo({ url: "/pages/todos/todos" });
    }
  },

  switchToLogin() {
    this.setData({ mode: "login", error: "" });
  },

  switchToRegister() {
    this.setData({ mode: "register", error: "" });
  },

  onUsernameInput(event) {
    this.setData({ username: event.detail.value });
  },

  onPasswordInput(event) {
    this.setData({ password: event.detail.value });
  },

  onInviteInput(event) {
    this.setData({ inviteCode: event.detail.value });
  },

  async submit() {
    if (this.data.submitting) return;
    this.setData({ submitting: true, error: "" });

    try {
      const username = this.data.username.trim();
      const password = this.data.password;
      if (this.data.mode === "register") {
        await api.register(username, password, this.data.inviteCode.trim());
      } else {
        await api.login(username, password);
      }
      wx.redirectTo({ url: "/pages/todos/todos" });
    } catch (error) {
      this.setData({ error: error.message || "请求失败" });
    } finally {
      this.setData({ submitting: false });
    }
  },
});
