var getStoredUser = require("./utils/api").getStoredUser;

App({
  globalData: {
    user: null,
    reducedMotion: false
  },

  onLaunch: function() {
    this.globalData.user = getStoredUser();
    this.detectAccessibilityPrefs();
  },

  detectAccessibilityPrefs: function() {
    try {
      var fontSizeSetting = 16;
      var platform = "";
      var system = "";

      try {
        var sysSetting = wx.getSystemSetting();
        fontSizeSetting = sysSetting.fontSizeSetting || 16;
      } catch (e) {
        // getSystemSetting may not be available in older base libraries
      }

      try {
        var deviceInfo = wx.getDeviceInfo();
        platform = deviceInfo.platform || "";
        system = deviceInfo.system || "";
      } catch (e) {
        // getDeviceInfo may not be available in older base libraries
      }

      // Detect reduced motion preference:
      // - Large font sizes often correlate with accessibility needs
      // - Older Android versions benefit from reduced motion for performance
      this.globalData.reducedMotion = fontSizeSetting > 20;

      if (platform === "android" && system) {
        var match = system.match(/Android\s+(\d+)/);
        if (match && parseInt(match[1], 10) <= 7) {
          this.globalData.reducedMotion = true;
        }
      }
    } catch (err) {
      this.globalData.reducedMotion = false;
    }
  }
});
