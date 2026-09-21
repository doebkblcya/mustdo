const ADD_MODE_KEY = "mustdo_add_mode";
const GUIDE_VERSION = 1;

function guideKey(userId) {
  return "mustdo_guide_v" + GUIDE_VERSION + "_user_" + String(userId || "unknown");
}

function getAddMode() {
  return wx.getStorageSync(ADD_MODE_KEY) === "confirm" ? "confirm" : "auto";
}

function setAddMode(mode) {
  const normalized = mode === "confirm" ? "confirm" : "auto";
  wx.setStorageSync(ADD_MODE_KEY, normalized);
  return normalized;
}

function hasSeenGuide(userId) {
  return wx.getStorageSync(guideKey(userId)) === true;
}

function markGuideSeen(userId) {
  wx.setStorageSync(guideKey(userId), true);
}

module.exports = {
  ADD_MODE_KEY,
  GUIDE_VERSION,
  getAddMode,
  setAddMode,
  hasSeenGuide,
  markGuideSeen,
};
