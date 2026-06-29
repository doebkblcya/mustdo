const { API_BASE_URL, WS_BASE_URL } = require("../config");

const TOKEN_KEY = "todo_analyzer_token";
const USER_KEY = "todo_analyzer_user";

function trimSlash(value) {
  return value.replace(/\/$/, "");
}

function apiUrl(path) {
  return `${trimSlash(API_BASE_URL)}${path}`;
}

function voiceStreamUrl() {
  return `${trimSlash(WS_BASE_URL)}/api/voice/stream`;
}

function getToken() {
  return wx.getStorageSync(TOKEN_KEY) || "";
}

function setSession(auth) {
  wx.setStorageSync(TOKEN_KEY, auth.token);
  wx.setStorageSync(USER_KEY, auth.user);
}

function clearSession() {
  wx.removeStorageSync(TOKEN_KEY);
  wx.removeStorageSync(USER_KEY);
}

function getStoredUser() {
  return wx.getStorageSync(USER_KEY) || null;
}

function request(path, options = {}) {
  const token = getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  return new Promise((resolve, reject) => {
    wx.request({
      url: apiUrl(path),
      method: options.method || "GET",
      data: options.data,
      header: headers,
      success(response) {
        const statusCode = response.statusCode || 0;
        if (statusCode >= 200 && statusCode < 300) {
          resolve(response.data);
          return;
        }
        reject(apiError(response.data, statusCode));
      },
      fail(error) {
        reject(new Error(error.errMsg || "网络请求失败"));
      },
    });
  });
}

function apiError(data, statusCode) {
  const message =
    data && typeof data.message === "string"
      ? data.message
      : data && data.detail
        ? String(data.detail)
        : `请求失败：${statusCode}`;
  const error = new Error(message);
  error.statusCode = statusCode;
  error.payload = data;
  return error;
}

async function login(username, password) {
  const result = await request("/api/auth/token/login", {
    method: "POST",
    data: { username, password },
  });
  setSession(result);
  return result.user;
}

async function register(username, password, inviteCode) {
  const result = await request("/api/auth/token/register", {
    method: "POST",
    data: { username, password, invite_code: inviteCode },
  });
  setSession(result);
  return result.user;
}

async function logout() {
  try {
    await request("/api/auth/logout", { method: "POST" });
  } finally {
    clearSession();
  }
}

function getMe() {
  return request("/api/me");
}

function listTodos() {
  return request("/api/todos");
}

function updateTodo(id, data) {
  return request(`/api/todos/${id}`, {
    method: "PATCH",
    data,
  });
}

function deleteTodo(id) {
  return request(`/api/todos/${id}`, {
    method: "DELETE",
  });
}

function createTodosFromTranscript(transcript) {
  return request("/api/todos/ai", {
    method: "POST",
    data: { transcript },
  });
}

module.exports = {
  apiUrl,
  voiceStreamUrl,
  getToken,
  getStoredUser,
  clearSession,
  login,
  register,
  logout,
  getMe,
  listTodos,
  updateTodo,
  deleteTodo,
  createTodosFromTranscript,
  request,
};
