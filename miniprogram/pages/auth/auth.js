const api = require("../../utils/api");
const spring = api.spring;

Page({
  data: {
    mode: "login",
    username: "",
    password: "",
    inviteCode: "",
    error: "",
    submitting: false,
    passwordVisible: false,
    // Pill animation
    pillX: 0,
    pillWidth: 0,
    // Panel entrance
    panelOpacity: 0,
    panelTranslateY: 24,
  },

  _pillSpring: null,
  _panelSpring: null,
  _tabPositions: null,
  _tabWidth: 0,
  _measured: false,

  onLoad() {
    if (api.getToken()) {
      wx.redirectTo({ url: "/pages/todos/todos" });
      return;
    }
    // Measure tab positions for pill, then animate entrance
    this.measureTabs();
  },

  measureTabs() {
    // Small delay so layout is painted before querying
    setTimeout(() => {
      const query = wx.createSelectorQuery();
      query.selectAll(".auth-tab").boundingClientRect();
      query.select(".auth-tabs").boundingClientRect();
      query.exec((res) => {
        const tabs = res[0];
        const container = res[1];
        if (!tabs || !container || tabs.length < 2) {
          // Fallback — try once more
          setTimeout(() => this.measureTabs(), 100);
          return;
        }
        this._tabPositions = tabs.map((t) => t.left - container.left);
        this._tabWidth = tabs[0].width;
        this._measured = true;

        // Set initial pill at login tab
        const targetX = this._tabPositions[0];
        this.setData({
          pillX: targetX,
          pillWidth: this._tabWidth,
        });

        // Entrance animation
        this.animatePanelEntrance();
      });
    }, 80);
  },

  animatePanelEntrance() {
    this.setData({ panelOpacity: 1 });
    this._panelSpring = spring(0, {
      damping: 0.8,
      response: 0.4,
      onUpdate: (value) => {
        this.setData({ panelTranslateY: value });
      },
    });
  },

  switchToLogin() {
    this.setData({ mode: "login", error: "" });
    this.animatePill(0);
  },

  switchToRegister() {
    this.setData({ mode: "register", error: "" });
    this.animatePill(1);
  },

  animatePill(tabIndex) {
    if (!this._measured || !this._tabPositions) return;
    const targetX = this._tabPositions[tabIndex];
    if (this._pillSpring) {
      this._pillSpring.retarget(targetX);
    } else {
      this.setData({ pillX: targetX });
    }
    // Start a new spring from the current screen value
    if (this._pillSpring) this._pillSpring.stop();
    this._pillSpring = spring(targetX, {
      damping: 0.8,
      response: 0.3,
      initialVelocity: 0,
      onUpdate: (value) => {
        this.setData({ pillX: value });
      },
    });
  },

  togglePasswordVisible() {
    wx.vibrateShort({ type: "light" });
    this.setData({ passwordVisible: !this.data.passwordVisible });
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
