const preferences = require("../../utils/preferences");
const api = require("../../utils/api");

function formatDurationPair(usedSeconds, totalSeconds) {
  const used = Math.max(0, Number(usedSeconds) || 0);
  const total = Math.max(0, Number(totalSeconds) || 0);
  if (total < 60) return Math.round(used) + " / " + Math.round(total) + " 秒";
  if (total < 3600) {
    return Math.round(used / 60) + " / " + Math.round(total / 60) + " 分钟";
  }
  const usedHours = Math.round(used / 360) / 10;
  const totalHours = Math.round(total / 360) / 10;
  return usedHours + " / " + totalHours + " 小时";
}

function formatTokens(tokens) {
  return String(Math.max(0, Math.round(Number(tokens) || 0))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function usedPercent(used, total) {
  const limit = Math.max(0, Number(total) || 0);
  if (!limit) return 0;
  return Math.max(0, Math.min(100, Math.round((Number(used) || 0) / limit * 100)));
}

function quotaView(quota) {
  const asr = quota.asr;
  const ai = quota.ai;
  return {
    asr: {
      enabled: asr.enabled,
      unlimited: asr.unlimited,
      value: !asr.enabled
        ? "已停用"
        : (asr.unlimited
          ? "无限"
          : formatDurationPair(asr.used_seconds, asr.total_seconds)),
      showProgress: asr.enabled && !asr.unlimited,
      usedPercent: usedPercent(asr.used_seconds, asr.total_seconds),
    },
    ai: {
      enabled: ai.enabled,
      unlimited: ai.unlimited,
      value: !ai.enabled
        ? "已停用"
        : (ai.unlimited
          ? "无限"
          : formatTokens(ai.used_tokens) + " / " + formatTokens(ai.total_tokens)),
      showProgress: ai.enabled && !ai.unlimited,
      usedPercent: usedPercent(ai.used_tokens, ai.total_tokens),
    },
  };
}

Page({
  data: {
    statusBarHeight: 0,
    headerRightOffset: 12,
    navTop: 24,
    navHeight: 32,
    addMode: "auto",
    quotaLoading: false,
    quotaError: "",
    quotaView: null,
    guideVisible: false,
  },

  onLoad() {
    const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    const menuButton = wx.getMenuButtonBoundingClientRect ? wx.getMenuButtonBoundingClientRect() : null;
    this.setData({
      statusBarHeight: windowInfo.statusBarHeight || 0,
      headerRightOffset: menuButton ? windowInfo.windowWidth - menuButton.left + 4 : 12,
      navTop: menuButton ? menuButton.top : (windowInfo.statusBarHeight || 0),
      navHeight: menuButton ? menuButton.height : 32,
    });
  },

  onShow() {
    this.setData({ addMode: preferences.getAddMode() });
    this.loadQuota();
  },

  loadQuota() {
    this.setData({ quotaLoading: true, quotaError: "" });
    api.getQuota()
      .then((quota) => {
        this.setData({
          quotaLoading: false,
          quotaError: "",
          quotaView: quotaView(quota),
        });
      })
      .catch((error) => {
        this.setData({
          quotaLoading: false,
          quotaError: error.message || "额度加载失败",
        });
      });
  },

  retryQuota() {
    this.loadQuota();
  },

  selectAddMode(event) {
    const mode = event.currentTarget.dataset.mode;
    this.setData({ addMode: preferences.setAddMode(mode) });
    wx.vibrateShort({ type: "light" });
  },

  openGuide() {
    this.setData({ guideVisible: true });
  },

  closeGuide() {
    const user = api.getStoredUser() || {};
    preferences.markGuideSeen(user.id);
    this.setData({ guideVisible: false });
  },
});
