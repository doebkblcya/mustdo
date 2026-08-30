const preferences = require("../../utils/preferences");

Page({
  data: {
    statusBarHeight: 0,
    headerRightOffset: 12,
    navTop: 24,
    navHeight: 32,
    addMode: "auto",
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
  },

  selectAddMode(event) {
    const mode = event.currentTarget.dataset.mode;
    this.setData({ addMode: preferences.setAddMode(mode) });
    wx.vibrateShort({ type: "light" });
  },
});
