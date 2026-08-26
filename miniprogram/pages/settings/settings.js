const preferences = require("../../utils/preferences");

Page({
  data: {
    addMode: "auto",
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
