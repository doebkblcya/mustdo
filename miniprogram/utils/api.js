var config = require("../config");

var API_BASE_URL = config.API_BASE_URL;

var TOKEN_KEY = "mustdo_token";
var USER_KEY = "mustdo_user";

function apiUrl(path) {
  return API_BASE_URL.replace(/\/$/, "") + path;
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

var _reloginPromise = null;

function _relogin() {
  if (_reloginPromise) return _reloginPromise;
  clearSession();
  // On failure, rethrow so callers (request / uploadVoice retries) surface the
  // real error instead of retrying with an empty token.
  _reloginPromise = wechatLogin().then(
    function() { _reloginPromise = null; },
    function(err) { _reloginPromise = null; throw err; }
  );
  return _reloginPromise;
}

function request(path, options) {
  var opts = options || {};
  var retry = !!opts._retry;
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
        // Session expired: silently re-login via WeChat, then retry once.
        if (statusCode === 401 && !retry && path !== "/api/auth/wechat") {
          _relogin()
            .then(function() {
              var retryOpts = {};
              Object.keys(opts).forEach(function(k) { retryOpts[k] = opts[k]; });
              retryOpts._retry = true;
              resolve(request(path, retryOpts));
            })
            .catch(function(err) { reject(err); });
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

function wechatLogin() {
  return new Promise(function(resolve, reject) {
    wx.login({
      success: function(res) {
        if (!res.code) {
          reject(new Error("微信登录失败，请重试"));
          return;
        }
        request("/api/auth/wechat", {
          method: "POST",
          data: { code: res.code }
        }).then(function(result) {
          setSession(result);
          resolve(result);
        }).catch(reject);
      },
      fail: function() {
        reject(new Error("微信登录失败，请重试"));
      }
    });
  });
}

function redeemInvite(code) {
  return request("/api/invites/redeem", {
    method: "POST",
    data: { code: code }
  });
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

// 设置/更新待办提醒（一次性订阅消息）
function setReminder(todoId, remindAt) {
  return request("/api/todos/" + todoId + "/reminder", {
    method: "PUT",
    data: { remind_at: remindAt },
  });
}

function deleteReminder(todoId) {
  return request("/api/todos/" + todoId + "/reminder", { method: "DELETE" });
}

// 垃圾桶列表：type = 'deleted' | 'overdue'，缺省返回计数摘要
function listTrash(type) {
  return request("/api/trash" + (type ? "?type=" + type : ""));
}

function parseTodos(transcript, source) {
  return request("/api/todos/parse", {
    method: "POST",
    data: { transcript: transcript, source: source || "voice" }
  });
}

function batchCreateTodos(items) {
  return request("/api/todos/batch", {
    method: "POST",
    data: { items: items }
  });
}

function organizeTodos(data) {
  return request("/api/todos/organize", {
    method: "POST",
    data: data
  });
}

function uploadVoice(filePath, onUploaded) {
  return uploadVoiceOnce(filePath, false, onUploaded);
}

function uploadVoiceOnce(filePath, retried, onUploaded) {
  var token = getToken();
  return new Promise(function(resolve, reject) {
    var uploadedNotified = false;
    var uploadTask = wx.uploadFile({
      url: apiUrl("/api/voice/transcriptions"),
      filePath: filePath,
      name: "file",
      header: {
        Authorization: "Bearer " + token,
      },
      success: function(res) {
        var statusCode = res.statusCode || 0;
        if (statusCode >= 200 && statusCode < 300) {
          try {
            resolve(JSON.parse(res.data));
          } catch (_e) {
            reject(new Error("语音服务返回格式异常"));
          }
          return;
        }
        // Session expired: silently re-login via WeChat, then re-upload once.
        if (statusCode === 401 && !retried) {
          _relogin()
            .then(function() {
              resolve(uploadVoiceOnce(filePath, true, onUploaded));
            })
            .catch(reject);
          return;
        }
        try {
          reject(apiError(JSON.parse(res.data), statusCode));
        } catch (_e) {
          reject(new Error("请求失败：" + statusCode));
        }
      },
      fail: function(err) {
        reject(new Error(err.errMsg || "上传失败"));
      },
    });
    if (uploadTask && uploadTask.onProgressUpdate && onUploaded) {
      uploadTask.onProgressUpdate(function(progress) {
        if (!uploadedNotified && progress.progress >= 100) {
          uploadedNotified = true;
          onUploaded();
        }
      });
    }
  });
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
  getToken: getToken,
  getStoredUser: getStoredUser,
  clearSession: clearSession,
  wechatLogin: wechatLogin,
  redeemInvite: redeemInvite,
  listTodos: listTodos,
  updateTodo: updateTodo,
  deleteTodo: deleteTodo,
  setReminder: setReminder,
  deleteReminder: deleteReminder,
  listTrash: listTrash,
  parseTodos: parseTodos,
  batchCreateTodos: batchCreateTodos,
  organizeTodos: organizeTodos,
  uploadVoice: uploadVoice,
  request: request,
  // Spring physics
  spring: spring,
  rubberband: rubberband,
  project: project,
  VelocityTracker: VelocityTracker
};
