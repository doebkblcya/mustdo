const { getStoredUser } = require("./utils/api");

App({
  globalData: {
    user: null,
  },

  onLaunch() {
    this.globalData.user = getStoredUser();
  },
});
