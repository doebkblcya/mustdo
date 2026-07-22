var config = require("../config");

var API_BASE_URL = config.API_BASE_URL;
var WS_BASE_URL = config.WS_BASE_URL;

var TOKEN_KEY = "todo_analyzer_token";
var USER_KEY = "todo_analyzer_user";

function trimSlash(value) {
  return value.replace(/\/$/, "");
}

function apiUrl(path) {
  return trimSlash(API_BASE_URL) + path;
}

function voiceStreamUrl() {
  return trimSlash(WS_BASE_URL) + "/api/voice/stream";
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

function request(path, options) {
  var opts = options || {};
  var token = getToken();
  var headers = { "Content-Type": "application/json" };
  if (opts.headers) {
    Object.keys(opts.headers).forEach(function(k) {
      headers[k] = opts.headers[k];
    });
  }
  if (token) {
    headers.Authorization = "Bearer " + token;
  }

  return new Promise(function(resolve, reject) {
    wx.request({
      url: apiUrl(path),
      method: opts.method || "GET",
      data: opts.data,
      header: headers,
      success: function(response) {
        var statusCode = response.statusCode || 0;
        if (statusCode >= 200 && statusCode < 300) {
          resolve(response.data);
          return;
        }
        reject(apiError(response.data, statusCode));
      },
      fail: function(error) {
        reject(new Error(error.errMsg || "网络请求失败"));
      }
    });
  });
}

function apiError(data, statusCode) {
  var message = (data && typeof data.message === "string")
    ? data.message
    : (data && data.detail ? String(data.detail) : "请求失败：" + statusCode);
  var error = new Error(message);
  error.statusCode = statusCode;
  error.payload = data;
  return error;
}

function login(username, password) {
  return request("/api/auth/token/login", {
    method: "POST",
    data: { username: username, password: password }
  }).then(function(result) {
    setSession(result);
    return result.user;
  });
}

function register(username, password, inviteCode) {
  return request("/api/auth/token/register", {
    method: "POST",
    data: { username: username, password: password, invite_code: inviteCode }
  }).then(function(result) {
    setSession(result);
    return result.user;
  });
}

function logout() {
  return request("/api/auth/logout", { method: "POST" }).then(function() {}, function() {}).then(function() {
    clearSession();
  });
}

function getMe() {
  return request("/api/me");
}

function listTodos() {
  return request("/api/todos");
}

function updateTodo(id, data) {
  return request("/api/todos/" + id, { method: "PATCH", data: data });
}

function deleteTodo(id) {
  return request("/api/todos/" + id, { method: "DELETE" });
}

function createTodosFromTranscript(transcript) {
  return request("/api/todos/ai", { method: "POST", data: { transcript: transcript } });
}

// ============================================================
// Spring physics engine (Apple Design Fluid Interfaces)
// ============================================================

function rubberband(overshoot, dimension, constant) {
  var c = constant != null ? constant : 0.55;
  return (overshoot * dimension * c) / (dimension + c * Math.abs(overshoot));
}

function project(velocity, decelerationRate) {
  var d = decelerationRate != null ? decelerationRate : 0.998;
  return (velocity / 1000) * d / (1 - d);
}

function VelocityTracker() {
  this.maxSamples = 5;
  this.points = [];
}

VelocityTracker.prototype.addPoint = function(y, t) {
  this.points.push({ y: y, t: t });
  if (this.points.length > this.maxSamples) {
    this.points.shift();
  }
};

VelocityTracker.prototype.reset = function(y, t) {
  this.points = [{ y: y, t: t }];
};

VelocityTracker.prototype.velocity = function() {
  if (this.points.length < 2) return 0;
  var a = this.points[0];
  var b = this.points[this.points.length - 1];
  var dt = (b.t - a.t) / 1000;
  if (dt <= 0) return 0;
  return (b.y - a.y) / dt;
};

function spring(target, options) {
  var opts = options || {};
  var damping = opts.damping != null ? opts.damping : 1.0;
  var response = opts.response != null ? opts.response : 0.4;
  var initialVelocity = opts.initialVelocity || 0;
  var onUpdate = opts.onUpdate || null;
  var onComplete = opts.onComplete || null;
  var onStop = opts.onStop || null;

  var zeta = Math.max(damping, 0.01);
  var settleTime = Math.max(response, 0.05);
  var omegaN = 4.605 / (zeta * settleTime);
  var stiffness = omegaN * omegaN;
  var dampingC = 2 * zeta * omegaN;

  var value = target;
  var velocity = initialVelocity;
  var dest = target;
  var timer = null;
  var done = false;

  function tick() {
    if (done) return;
    var dt = 0.016;
    var disp = value - dest;
    var accel = -stiffness * disp - dampingC * velocity;
    velocity = velocity + accel * dt;
    value = value + velocity * dt;

    if (Math.abs(disp) < 0.05 && Math.abs(velocity) < 0.1) {
      value = dest;
      velocity = 0;
      done = true;
      if (timer) { clearInterval(timer); timer = null; }
      if (onUpdate) onUpdate(value);
      if (onComplete) onComplete();
      return;
    }
    if (onUpdate) onUpdate(value);
  }

  timer = setInterval(tick, 16);
  tick();

  return {
    retarget: function(newTarget, newVelocity) {
      dest = newTarget;
      if (newVelocity != null) velocity = newVelocity;
      if (done) { done = false; timer = setInterval(tick, 16); tick(); }
    },
    stop: function() {
      if (timer) { clearInterval(timer); timer = null; }
      if (!done && onStop) { done = true; onStop(); }
      done = true;
    }
  };
}

// ============================================================

module.exports = {
  // API
  apiUrl: apiUrl,
  voiceStreamUrl: voiceStreamUrl,
  getToken: getToken,
  getStoredUser: getStoredUser,
  clearSession: clearSession,
  login: login,
  register: register,
  logout: logout,
  getMe: getMe,
  listTodos: listTodos,
  updateTodo: updateTodo,
  deleteTodo: deleteTodo,
  createTodosFromTranscript: createTodosFromTranscript,
  request: request,
  // Spring physics
  spring: spring,
  rubberband: rubberband,
  project: project,
  VelocityTracker: VelocityTracker
};
