const ADD_MODE_KEY = "mustdo_add_mode";

function getAddMode() {
  return wx.getStorageSync(ADD_MODE_KEY) === "confirm" ? "confirm" : "auto";
}

function setAddMode(mode) {
  const normalized = mode === "confirm" ? "confirm" : "auto";
  wx.setStorageSync(ADD_MODE_KEY, normalized);
  return normalized;
}

module.exports = {
  ADD_MODE_KEY,
  getAddMode,
  setAddMode,
};
