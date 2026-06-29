const API_BASE_URL = "https://doebkblcya.com";

function websocketBaseUrl() {
  if (API_BASE_URL.startsWith("https://")) {
    return API_BASE_URL.replace(/^https:\/\//, "wss://");
  }
  return API_BASE_URL.replace(/^http:\/\//, "ws://");
}

module.exports = {
  API_BASE_URL,
  WS_BASE_URL: websocketBaseUrl(),
};
