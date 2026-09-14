const preferences = require("../../utils/preferences");
const api = require("../../utils/api");

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) return Math.round(value) + " 秒";
  const minutes = value / 60;
  if (minutes < 60) return Math.round(minutes) + " 分钟";
  const hours = minutes / 60;
  return (Math.round(hours * 10) / 10) + " 小时";
}

function formatTokens(tokens) {
  return String(Math.max(0, Math.round(Number(tokens) || 0))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function remainingPercent(remaining, total, unlimited, enabled) {
  if (!enabled) return 0;
  if (unlimited) return 100;
  const limit = Math.max(0, Number(total) || 0);
  if (!limit) return 0;
  return Math.max(0, Math.min(100, Math.round((Number(remaining) || 0) / limit * 100)));
}

function quotaView(quota) {
  const asr = quota.asr;
  const ai = quota.ai;
  return {
    asr: {
      enabled: asr.enabled,
      unlimited: asr.unlimited,
      status: !asr.enabled
        ? "已停用"
        : (asr.unlimited ? "无限额度" : ""),
      summary: !asr.enabled
        ? "当前不可使用"
        : (asr.unlimited ? "不设总额度上限" : "总额度 " + formatDuration(asr.total_seconds)),
      remainingPercent: remainingPercent(
        asr.remaining_seconds,
        asr.total_seconds,
        asr.unlimited,
        asr.enabled
      ),
    },
    ai: {
      enabled: ai.enabled,
      unlimited: ai.unlimited,
      status: !ai.enabled
        ? "已停用"
        : (ai.unlimited ? "无限额度" : ""),
      summary: !ai.enabled
        ? "当前不可使用"
        : (ai.unlimited ? "不设总额度上限" : "总额度 " + formatTokens(ai.total_tokens) + " tokens"),
      remainingPercent: remainingPercent(
        ai.remaining_tokens,
        ai.total_tokens,
        ai.unlimited,
        ai.enabled
      ),
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
});
