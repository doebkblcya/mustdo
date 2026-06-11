const SUCCESS_CLOSE_MS = 1800;
const MAX_RECORDING_MS = 30_000;
const MIN_RECORDING_SECONDS = 0.5;
const TARGET_SAMPLE_RATE = 16_000;

const state = {
  user: null,
  authMode: "login",
  authError: "",
  todos: null,
  activeView: "today",
  editingId: null,
  editValues: {},
  overlay: null,
  recording: null,
};

const app = document.querySelector("#app");

const icons = {
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  circle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
  save: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></svg>',
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(formatApiError(data.detail));
    error.status = response.status;
    throw error;
  }
  return data;
}

function formatApiError(detail) {
  if (!detail) return "请求失败";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "";
        const message = item.msg || "参数不合法";
        return field ? `${field}: ${message}` : message;
      })
      .join("；");
  }
  if (typeof detail === "object") {
    return detail.message || detail.msg || JSON.stringify(detail);
  }
  return String(detail);
}

function formatDate(value) {
  const date = new Date(`${value}T00:00:00+08:00`);
  return date.toLocaleDateString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    weekday: "short",
  });
}

function todayString() {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date()).map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function isVisibleTodo(todo) {
  return todo.due_date >= todayString();
}

function render() {
  if (!state.user) {
    renderAuth();
    return;
  }
  renderDashboard();
}

function renderAuth() {
  const isRegister = state.authMode === "register";
  app.innerHTML = `
    <main class="auth-screen">
      <section class="auth-panel">
        <h1>Todo Analyzer</h1>
        <div class="auth-tabs">
          <button type="button" class="${!isRegister ? "active" : ""}" data-auth-mode="login">登录</button>
          <button type="button" class="${isRegister ? "active" : ""}" data-auth-mode="register">注册</button>
        </div>
        <form class="auth-form" id="authForm">
          <input class="field" name="username" autocomplete="username" placeholder="用户名" required />
          <input class="field" name="password" type="password" autocomplete="${isRegister ? "new-password" : "current-password"}" placeholder="${isRegister ? "密码，至少 8 位" : "密码"}" required />
          ${
            isRegister
              ? '<input class="field" name="invite_code" autocomplete="one-time-code" placeholder="邀请码" required />'
              : ""
          }
          <div class="form-error">${escapeHtml(state.authError)}</div>
          <button class="primary-button" type="submit">${isRegister ? "注册" : "登录"}</button>
        </form>
      </section>
    </main>
  `;
}

function renderDashboard() {
  const todos = state.todos || {
    today_date: todayString(),
    tomorrow_date: "",
    groups: { today: [], tomorrow: [], upcoming: [] },
  };
  const current = getCurrentView(todos);

  app.innerHTML = `
    <main class="app-shell">
      <header class="topbar">
        <div class="brand">
          <h1>Todo Analyzer</h1>
        </div>
        <div class="user-actions">
          <span class="user-chip">${escapeHtml(state.user.username)}</span>
          <button class="secondary-button" type="button" id="logoutButton">登出</button>
        </div>
      </header>
      ${renderViewTabs(todos)}
      ${renderSchedulePage(current)}
      <div class="voice-dock">
        <button class="voice-button ${state.recording ? "recording" : ""}" id="voiceButton" type="button" aria-label="按住说话" title="按住说话">
          ${icons.mic}
        </button>
      </div>
      ${renderOverlay()}
    </main>
  `;
}

function getViewConfigs(todos) {
  const groups = todos.groups || {};
  return [
    {
      key: "today",
      title: "今天",
      dateLabel: todos.today_date,
      items: groups.today || [],
    },
    {
      key: "tomorrow",
      title: "明天",
      dateLabel: todos.tomorrow_date,
      items: groups.tomorrow || [],
    },
    {
      key: "upcoming",
      title: "后续",
      dateLabel: "",
      items: groups.upcoming || [],
    },
  ];
}

function getCurrentView(todos) {
  return getViewConfigs(todos).find((view) => view.key === state.activeView) || getViewConfigs(todos)[0];
}

function renderViewTabs(todos) {
  const activeIndex = getViewConfigs(todos).findIndex((view) => view.key === state.activeView);
  return `
    <nav class="view-tabs" aria-label="待办时间范围" style="--active-index: ${Math.max(activeIndex, 0)};">
      <span class="view-tab-indicator" aria-hidden="true"></span>
      ${getViewConfigs(todos)
        .map((view) => {
          const count = view.items.filter(isVisibleTodo).length;
          const active = view.key === state.activeView;
          const label =
            view.key === "upcoming" ? `${count} 项` : view.dateLabel ? formatDate(view.dateLabel) : "";
          return `
            <button class="view-tab ${active ? "active" : ""}" type="button" data-view="${view.key}" aria-pressed="${active}">
              <span class="view-tab-title">${view.title}</span>
              <span class="view-tab-meta">${escapeHtml(label)}</span>
            </button>
          `;
        })
        .join("")}
    </nav>
  `;
}

function renderSchedulePage(view) {
  const visible = (view.items || []).filter(isVisibleTodo);
  const untimed = visible.filter((todo) => !todo.due_time);
  const timed = visible.filter((todo) => todo.due_time);
  const dateLabel =
    view.key === "upcoming" ? `${visible.length} 项` : view.dateLabel ? formatDate(view.dateLabel) : "";

  return `
    <section class="schedule-page" data-view-panel="${view.key}">
      <div class="schedule-header">
        <div>
          <h2 class="schedule-title">${view.title}</h2>
          <div class="schedule-date">${escapeHtml(dateLabel)}</div>
        </div>
        <span class="schedule-count">${visible.length} 项</span>
      </div>
      <div class="schedule-content">
        ${visible.length ? renderUntimedSection(untimed, view) + renderTimelineSection(timed, view) : '<div class="empty large">暂无待办</div>'}
      </div>
    </section>
  `;
}

function renderUntimedSection(items, view) {
  if (!items.length) return "";
  return `
    <section class="untimed-section">
      <div class="section-label">
        <span>无具体时间</span>
        <span>${items.length} 项</span>
      </div>
      <div class="untimed-list">
        ${items.map((todo) => renderTodo(todo, { showDate: view.key === "upcoming" })).join("")}
      </div>
    </section>
  `;
}

function renderTimelineSection(items, view) {
  if (!items.length) return "";
  return `
    <section class="timeline-section">
      <div class="section-label">
        <span>时间线</span>
        <span>${items.length} 项</span>
      </div>
      <div class="timeline">
        ${items.map((todo) => renderTimelineItem(todo, view)).join("")}
      </div>
    </section>
  `;
}

function renderTimelineItem(todo, view) {
  const markerDate = view.key === "upcoming" ? `<span>${escapeHtml(formatDate(todo.due_date))}</span>` : "";
  return `
    <div class="timeline-row">
      <div class="timeline-marker">
        ${markerDate}
        <strong>${escapeHtml(todo.due_time)}</strong>
      </div>
      <div class="timeline-node" aria-hidden="true"></div>
      <div class="timeline-card">
        ${renderTodo(todo, { compactMeta: true, showDate: view.key === "upcoming" })}
      </div>
    </div>
  `;
}

function renderTodo(todo, options = {}) {
  const done = todo.status === "done";
  const isEditing = state.editingId === todo.id;
  const metaParts = [];
  if (options.showDate) metaParts.push(formatDate(todo.due_date));
  if (!options.compactMeta && todo.due_time) metaParts.push(todo.due_time);
  const meta = metaParts.join(" ");
  return `
    <article class="todo-item ${done ? "done" : ""}" data-todo-id="${todo.id}">
      <button class="status-button ${done ? "is-done" : ""}" type="button" data-action="toggle" title="${done ? "标记未完成" : "标记完成"}" aria-label="${done ? "标记未完成" : "标记完成"}">
        ${done ? icons.check : icons.circle}
      </button>
      <div class="todo-content">
        <div class="todo-title">${escapeHtml(todo.content)}</div>
        ${meta ? `<div class="todo-meta">${escapeHtml(meta)}</div>` : ""}
      </div>
      <div class="todo-actions">
        <button class="icon-button" type="button" data-action="edit" title="编辑" aria-label="编辑">${icons.edit}</button>
        <button class="icon-button icon-danger" type="button" data-action="delete" title="删除" aria-label="删除">${icons.trash}</button>
      </div>
      ${isEditing ? renderTodoEdit(todo) : ""}
    </article>
  `;
}

function renderTodoEdit(todo) {
  const values = state.editValues[todo.id] || {
    content: todo.content,
    due_date: todo.due_date,
    due_time: todo.due_time || "",
  };
  return `
    <form class="todo-edit" data-edit-form="${todo.id}">
      <input class="field" name="content" value="${escapeHtml(values.content)}" required maxlength="200" />
      <input class="field" name="due_date" type="date" value="${escapeHtml(values.due_date)}" required />
      <input class="field" name="due_time" type="time" value="${escapeHtml(values.due_time)}" />
      <button class="icon-button" type="submit" title="保存" aria-label="保存">${icons.save}</button>
      <button class="icon-button" type="button" data-action="cancel-edit" title="取消" aria-label="取消">${icons.close}</button>
    </form>
  `;
}

function renderOverlay() {
  if (!state.overlay) return "";
  const overlay = state.overlay;
  const busy = ["recording", "transcribing", "parsing"].includes(overlay.status);
  const titleMap = {
    recording: "正在录音",
    transcribing: "正在转文字",
    parsing: "正在解析待办",
    success: "已添加",
    error: "解析失败",
  };
  return `
    <div class="overlay-backdrop">
      <section class="parse-panel">
        <div class="parse-header">
          <h2 class="parse-title">${titleMap[overlay.status] || "处理中"}</h2>
          ${
            overlay.status === "error"
              ? `<button class="icon-button" type="button" data-action="close-overlay" title="关闭" aria-label="关闭">${icons.close}</button>`
              : ""
          }
        </div>
        <div class="parse-status">
          ${busy ? '<span class="spinner"></span>' : `<span class="status-dot ${overlay.status === "error" ? "error" : ""}"></span>`}
          <span>${escapeHtml(overlay.message || titleMap[overlay.status])}</span>
        </div>
        ${overlay.transcript ? `<div class="transcript-box">${escapeHtml(overlay.transcript)}</div>` : ""}
        ${
          overlay.items?.length
            ? `<div class="result-list">${overlay.items.map(renderResultRow).join("")}</div>`
            : ""
        }
        ${overlay.error ? `<div class="error-text">${escapeHtml(overlay.error)}</div>` : ""}
      </section>
    </div>
  `;
}

function renderResultRow(item) {
  const date = `${formatDate(item.due_date)}${item.due_time ? ` ${item.due_time}` : ""}`;
  return `
    <div class="result-row">
      <span>${escapeHtml(item.content)}</span>
      <span class="result-date">${escapeHtml(date)}</span>
    </div>
  `;
}

async function bootstrap() {
  try {
    state.user = await api("/api/me");
    await loadTodos();
  } catch {
    state.user = null;
  }
  render();
}

async function loadTodos() {
  state.todos = await api("/api/todos");
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form).entries());
  state.authError = "";
  render();
  try {
    const endpoint = state.authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const result = await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
    state.user = result.user;
    state.authError = "";
    await loadTodos();
    render();
  } catch (error) {
    state.authError = error.message;
    render();
  }
}

async function logout() {
  await api("/api/auth/logout", { method: "POST" }).catch(() => null);
  state.user = null;
  state.todos = null;
  render();
}

async function toggleTodo(todoId) {
  const todo = findTodo(todoId);
  if (!todo) return;
  await api(`/api/todos/${todoId}`, {
    method: "PATCH",
    body: JSON.stringify({ status: todo.status === "done" ? "pending" : "done" }),
  });
  await loadTodos();
  render();
}

async function saveTodo(todoId, form) {
  const formData = new FormData(form);
  const payload = {
    content: formData.get("content"),
    due_date: formData.get("due_date"),
    due_time: formData.get("due_time") || null,
  };
  await api(`/api/todos/${todoId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  state.editingId = null;
  delete state.editValues[todoId];
  await loadTodos();
  render();
}

async function deleteTodo(todoId) {
  if (!window.confirm("删除这条待办？")) return;
  await api(`/api/todos/${todoId}`, { method: "DELETE" });
  await loadTodos();
  render();
}

function findTodo(todoId) {
  const groups = state.todos?.groups || {};
  return [...(groups.today || []), ...(groups.tomorrow || []), ...(groups.upcoming || [])].find(
    (todo) => todo.id === todoId,
  );
}

async function startRecording() {
  if (state.recording) return;
  if (!navigator.mediaDevices?.getUserMedia) {
    showOverlay({ status: "error", error: "当前浏览器不支持录音" });
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContextClass();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const zeroGain = context.createGain();
    zeroGain.gain.value = 0;

    const chunks = [];
    processor.onaudioprocess = (event) => {
      chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    };
    source.connect(processor);
    processor.connect(zeroGain);
    zeroGain.connect(context.destination);

    state.recording = {
      stream,
      context,
      source,
      processor,
      zeroGain,
      chunks,
      startedAt: performance.now(),
      sampleRate: context.sampleRate,
      timeoutId: window.setTimeout(() => stopRecording(), MAX_RECORDING_MS),
    };
    showOverlay({ status: "recording", message: "松开后开始转写" });
  } catch {
    showOverlay({ status: "error", error: "无法使用麦克风" });
  }
}

async function stopRecording() {
  const recording = state.recording;
  if (!recording) return;
  window.clearTimeout(recording.timeoutId);
  state.recording = null;

  recording.processor.disconnect();
  recording.source.disconnect();
  recording.zeroGain.disconnect();
  recording.stream.getTracks().forEach((track) => track.stop());
  await recording.context.close().catch(() => null);

  try {
    const merged = mergeAudioChunks(recording.chunks);
    const downsampled = downsampleBuffer(merged, recording.sampleRate, TARGET_SAMPLE_RATE);
    const pcm = floatTo16BitPcm(downsampled);
    const duration = pcm.byteLength / (TARGET_SAMPLE_RATE * 2);
    if (duration < MIN_RECORDING_SECONDS) {
      showOverlay({ status: "error", error: "录音太短" });
      return;
    }
    await transcribeAndCreateTodos(pcm);
  } catch {
    showOverlay({ status: "error", error: "录音处理失败" });
  }
}

function mergeAudioChunks(chunks) {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
  if (inputSampleRate === outputSampleRate) return buffer;
  if (inputSampleRate < outputSampleRate) {
    throw new Error("Input sample rate is lower than target sample rate");
  }
  const ratio = inputSampleRate / outputSampleRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accumulator = 0;
    let count = 0;
    for (let index = offsetBuffer; index < nextOffsetBuffer && index < buffer.length; index += 1) {
      accumulator += buffer[index];
      count += 1;
    }
    result[offsetResult] = accumulator / count;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function floatTo16BitPcm(samples) {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

async function transcribeAndCreateTodos(pcmBuffer) {
  showOverlay({ status: "transcribing", message: "正在转文字" });
  const formData = new FormData();
  formData.append("file", new Blob([pcmBuffer], { type: "audio/pcm" }), "recording.pcm");

  try {
    const transcription = await api("/api/voice/transcriptions", {
      method: "POST",
      body: formData,
    });
    showOverlay({
      status: "parsing",
      transcript: transcription.transcript,
      message: "正在解析待办",
    });
    const result = await api("/api/todos/ai", {
      method: "POST",
      body: JSON.stringify({ transcript: transcription.transcript }),
    });
    await loadTodos();
    showOverlay({
      status: "success",
      transcript: result.transcript,
      items: result.items,
      message: `已添加 ${result.items.length} 项`,
    });
    render();
    window.setTimeout(() => {
      if (state.overlay?.status === "success") {
        state.overlay = null;
        render();
      }
    }, SUCCESS_CLOSE_MS);
  } catch (error) {
    showOverlay({ status: "error", error: error.message || "AI 有问题，未添加待办" });
  }
}

function showOverlay(overlay) {
  state.overlay = overlay;
  render();
}

app.addEventListener("click", async (event) => {
  const authModeButton = event.target.closest("[data-auth-mode]");
  if (authModeButton) {
    state.authMode = authModeButton.dataset.authMode;
    state.authError = "";
    render();
    return;
  }

  if (event.target.closest("#logoutButton")) {
    await logout();
    return;
  }

  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    state.activeView = viewButton.dataset.view;
    state.editingId = null;
    render();
    return;
  }

  const closeOverlay = event.target.closest('[data-action="close-overlay"]');
  if (closeOverlay) {
    state.overlay = null;
    render();
    return;
  }

  const todoEl = event.target.closest("[data-todo-id]");
  if (!todoEl) return;
  const todoId = Number(todoEl.dataset.todoId);
  const actionEl = event.target.closest("[data-action]");
  if (!actionEl) return;

  const action = actionEl.dataset.action;
  if (action === "toggle") {
    await toggleTodo(todoId);
  } else if (action === "edit") {
    const todo = findTodo(todoId);
    state.editingId = todoId;
    state.editValues[todoId] = {
      content: todo.content,
      due_date: todo.due_date,
      due_time: todo.due_time || "",
    };
    render();
  } else if (action === "cancel-edit") {
    state.editingId = null;
    delete state.editValues[todoId];
    render();
  } else if (action === "delete") {
    await deleteTodo(todoId);
  }
});

app.addEventListener("submit", async (event) => {
  if (event.target.id === "authForm") {
    await handleAuthSubmit(event);
    return;
  }

  const editForm = event.target.closest("[data-edit-form]");
  if (editForm) {
    event.preventDefault();
    await saveTodo(Number(editForm.dataset.editForm), editForm);
  }
});

app.addEventListener("pointerdown", async (event) => {
  const button = event.target.closest("#voiceButton");
  if (!button) return;
  event.preventDefault();
  button.setPointerCapture?.(event.pointerId);
  await startRecording();
});

app.addEventListener("pointerup", async (event) => {
  if (!state.recording) return;
  event.preventDefault();
  await stopRecording();
});

app.addEventListener("pointercancel", async () => {
  await stopRecording();
});

app.addEventListener("contextmenu", (event) => {
  if (event.target.closest("#voiceButton")) {
    event.preventDefault();
  }
});

bootstrap();

window.addEventListener("pointerup", async () => {
  if (state.recording) {
    await stopRecording();
  }
});
