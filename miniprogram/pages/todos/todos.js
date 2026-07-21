const api = require("../../utils/api");

const VIEW_META = {
  today: "今天",
  tomorrow: "明天",
  upcoming: "后续",
};

Page({
  data: {
    user: null,
    activeView: "today",
    viewTitle: "今天",
    viewDate: "",
    todayDate: "",
    items: [],
    todos: null,
    loading: false,
    error: "",
    recording: false,
    voiceMessage: "",
    transcript: "",
    editVisible: false,
    editClosing: false,
    editTodoId: null,
    editContent: "",
    editDate: "",
    editTime: "",
    editUseTime: false,
    editSubmitting: false,
  },

  recorder: null,
  socketTask: null,
  socketReady: false,
  recorderStarted: false,
  stopRequested: false,
  voiceEnded: false,
  voiceEndSent: false,
  voiceDone: false,
  pendingFrames: [],

  onLoad() {
    if (!api.getToken()) {
      wx.redirectTo({ url: "/pages/auth/auth" });
      return;
    }
    this.setData({ user: api.getStoredUser() });
    this.setupRecorder();
    this.loadTodos();
  },

  onUnload() {
    this.closeVoiceSocket();
  },

  onPullDownRefresh() {
    this.loadTodos().finally(() => {
      wx.stopPullDownRefresh();
    });
  },

  async loadTodos() {
    this.setData({ loading: true, error: "" });
    try {
      const todos = await api.listTodos();
      this.setData({ todos, loading: false, todayDate: todos.today_date || "" });
      this.applyActiveView(this.data.activeView);
    } catch (error) {
      if (error.statusCode === 401) {
        api.clearSession();
        wx.redirectTo({ url: "/pages/auth/auth" });
        return;
      }
      this.setData({ loading: false, error: error.message || "加载失败" });
    }
  },

  applyActiveView(view) {
    const todos = this.data.todos;
    const groups = todos && todos.groups ? todos.groups : {};
    const date = view === "today" ? todos && todos.today_date : view === "tomorrow" ? todos && todos.tomorrow_date : "";
    const items = (groups[view] || []).map((item) => ({
      ...item,
      meta: `${item.due_date}${item.due_time ? ` ${item.due_time}` : ""}`,
    }));
    this.setData({
      activeView: view,
      viewTitle: VIEW_META[view],
      viewDate: date || "",
      items,
    });
  },

  switchView(event) {
    this.applyActiveView(event.currentTarget.dataset.view);
  },

  async toggleTodo(event) {
    const id = Number(event.currentTarget.dataset.id);
    const currentStatus = event.currentTarget.dataset.status;
    const newStatus = currentStatus === "done" ? "pending" : "done";

    // Optimistic update — update items locally first
    const items = this.data.items.map((item) =>
      item.id === id ? { ...item, status: newStatus } : item
    );
    this.setData({ items });

    // Also patch todos.groups to stay consistent
    this.patchGroupItem(id, { status: newStatus });

    wx.vibrateShort({ type: "light" });

    try {
      await api.updateTodo(id, { status: newStatus });
    } catch (error) {
      // Revert on failure
      const revertedItems = this.data.items.map((item) =>
        item.id === id ? { ...item, status: currentStatus } : item
      );
      this.setData({ items: revertedItems });
      this.patchGroupItem(id, { status: currentStatus });
      wx.showToast({ title: error.message || "操作失败", icon: "none" });
    }
  },

  deleteTodo(event) {
    const id = Number(event.currentTarget.dataset.id);
    wx.showModal({
      title: "删除待办",
      content: "确定删除这条待办？",
      success: async (result) => {
        if (!result.confirm) return;

        // Optimistic — remove from local arrays
        const prevItems = this.data.items;
        const prevTodos = this.data.todos;
        this.setData({
          items: prevItems.filter((item) => item.id !== id),
          todos: this.removeFromGroups(prevTodos, id),
        });

        wx.vibrateShort({ type: "medium" });

        try {
          await api.deleteTodo(id);
        } catch (error) {
          // Revert on failure
          this.setData({ items: prevItems, todos: prevTodos });
          wx.showToast({ title: error.message || "删除失败", icon: "none" });
        }
      },
    });
  },

  removeFromGroups(todos, id) {
    if (!todos || !todos.groups) return todos;
    const groups = {};
    for (const key of ["today", "tomorrow", "upcoming"]) {
      groups[key] = (todos.groups[key] || []).filter((item) => item.id !== id);
    }
    return { ...todos, groups };
  },

  editTodo(event) {
    const id = Number(event.currentTarget.dataset.id);
    const todo = this.findTodo(id);
    if (!todo) {
      wx.showToast({ title: "待办不存在", icon: "none" });
      return;
    }
    // Clear any pending close timeout to prevent race condition
    if (this._editCloseTimer) {
      clearTimeout(this._editCloseTimer);
      this._editCloseTimer = null;
    }
    this.setData({
      editVisible: true,
      editClosing: false,
      editTodoId: todo.id,
      editContent: todo.content,
      editDate: todo.due_date,
      editTime: todo.due_time || "09:00",
      editUseTime: Boolean(todo.due_time),
      editSubmitting: false,
    });
  },

  findTodo(id) {
    const groups = this.data.todos && this.data.todos.groups ? this.data.todos.groups : {};
    return [...(groups.today || []), ...(groups.tomorrow || []), ...(groups.upcoming || [])].find((item) => item.id === id);
  },

  patchGroupItem(id, patch) {
    const todos = this.data.todos;
    if (!todos || !todos.groups) return;
    const groups = { ...todos.groups };
    for (const key of ["today", "tomorrow", "upcoming"]) {
      if (groups[key]) {
        groups[key] = groups[key].map((item) =>
          item.id === id ? { ...item, ...patch } : item
        );
      }
    }
    // Use silent data update — no setData needed since items already reflect the change
    this.data.todos = { ...todos, groups };
  },

  onEditContentInput(event) {
    this.setData({ editContent: event.detail.value });
  },

  onEditDateChange(event) {
    this.setData({ editDate: event.detail.value });
  },

  onEditTimeChange(event) {
    this.setData({ editTime: event.detail.value });
  },

  onEditUseTimeChange(event) {
    this.setData({ editUseTime: event.detail.value });
  },

  cancelEdit() {
    if (this.data.editSubmitting) return;
    // Trigger closing animation, then remove from DOM
    this.setData({ editClosing: true });
    this._editCloseTimer = setTimeout(() => {
      this._editCloseTimer = null;
      this.setData({ editVisible: false, editClosing: false, editTodoId: null, error: "" });
    }, 280);
  },

  noop() {},

  async submitEdit() {
    if (this.data.editSubmitting) return;
    const content = this.data.editContent.trim();
    if (!content) {
      wx.showToast({ title: "内容不能为空", icon: "none" });
      return;
    }
    this.setData({ editSubmitting: true });
    try {
      const patch = {
        content,
        due_date: this.data.editDate,
        due_time: this.data.editUseTime ? this.data.editTime : null,
      };
      await api.updateTodo(this.data.editTodoId, patch);

      // Update local data instead of full reload
      const todos = this.data.todos;
      if (todos && todos.groups) {
        for (const key of ["today", "tomorrow", "upcoming"]) {
          if (todos.groups[key]) {
            todos.groups[key] = todos.groups[key].map((item) =>
              item.id === this.data.editTodoId ? { ...item, ...patch } : item
            );
          }
        }
      }

      // Re-derive items for current view
      const items = ((todos && todos.groups && todos.groups[this.data.activeView]) || []).map((item) => ({
        ...item,
        meta: `${item.due_date}${item.due_time ? ` ${item.due_time}` : ""}`,
      }));

      this.setData({
        editClosing: true,
        editSubmitting: false,
        todos,
        items,
      });

      wx.vibrateShort({ type: "light" });

      this._editCloseTimer = setTimeout(() => {
        this._editCloseTimer = null;
        this.setData({ editVisible: false, editClosing: false, editTodoId: null });
      }, 280);
    } catch (error) {
      wx.showToast({ title: error.message || "保存失败", icon: "none" });
      this.setData({ editSubmitting: false });
    }
  },

  async logout() {
    await api.logout();
    wx.redirectTo({ url: "/pages/auth/auth" });
  },

  setupRecorder() {
    if (this.recorder) return;
    this.recorder = wx.getRecorderManager();

    this.recorder.onStart(() => {
      this.recorderStarted = true;
      if (this.stopRequested) {
        setTimeout(() => this.stopRecorder(), 80);
        return;
      }
      this.setData({
        recording: true,
        voiceMessage: this.socketReady ? "正在录音" : "正在准备语音服务",
      });
    });

    this.recorder.onFrameRecorded((event) => {
      if (event.frameBuffer) {
        this.sendOrQueueFrame(event.frameBuffer);
      }
    });

    this.recorder.onStop(() => {
      this.recorderStarted = false;
      this.voiceEnded = true;
      this.sendVoiceEndIfReady();
    });

    this.recorder.onError((error) => {
      this.recorderStarted = false;
      this.failVoice(error.errMsg || "录音失败");
    });
  },

  async startVoice() {
    if (this.data.recording) return;
    if (!api.getToken()) {
      wx.redirectTo({ url: "/pages/auth/auth" });
      return;
    }
    try {
      await this.ensureRecordPermission();
    } catch (_error) {
      this.failVoice("请先授权麦克风");
      return;
    }

    this.resetVoiceState();
    this.setData({
      recording: false,
      voiceMessage: "正在准备语音服务",
      transcript: "",
    });

    this.socketTask = wx.connectSocket({
      url: api.voiceStreamUrl(),
      header: {
        Authorization: `Bearer ${api.getToken()}`,
      },
    });
    this.bindVoiceSocket(this.socketTask);

    try {
      this.recorder.start({
        duration: 30000,
        sampleRate: 16000,
        numberOfChannels: 1,
        format: "pcm",
        frameSize: 4,
      });
    } catch (error) {
      this.failVoice(error.errMsg || error.message || "录音启动失败");
    }
  },

  ensureRecordPermission() {
    return new Promise((resolve, reject) => {
      wx.getSetting({
        success: (settings) => {
          if (settings.authSetting["scope.record"]) {
            resolve();
            return;
          }
          wx.authorize({
            scope: "scope.record",
            success: resolve,
            fail: reject,
          });
        },
        fail: reject,
      });
    });
  },

  stopVoice() {
    if (this.stopRequested || this.voiceDone) return;
    this.stopRequested = true;
    this.setData({ recording: false, voiceMessage: "正在等待最终文本" });
    this.voiceEnded = true;
    this.stopRecorder();
    this.sendVoiceEndIfReady();
  },

  stopRecorder() {
    if (!this.recorderStarted) {
      return;
    }
    try {
      this.recorder.stop();
    } catch (error) {
      this.recorderStarted = false;
    }
  },

  bindVoiceSocket(socketTask) {
    socketTask.onOpen(() => {
      return;
    });

    socketTask.onMessage((event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_error) {
        this.failVoice("语音服务返回格式异常");
        return;
      }

      if (message.type === "ready") {
        this.socketReady = true;
        this.flushVoiceFrames();
        this.setData({ voiceMessage: this.data.recording ? "正在录音" : "正在等待最终文本" });
        this.sendVoiceEndIfReady();
        return;
      }

      if (message.type === "partial") {
        this.setData({
          transcript: message.transcript || this.data.transcript,
          voiceMessage: "正在转文字",
        });
        return;
      }

      if (message.type === "final") {
        const transcript = message.transcript || "";
        this.setData({ transcript, voiceMessage: "正在解析待办" });
        this.voiceDone = true;
        this.closeVoiceSocket();
        this.createTodosFromVoice(transcript);
        return;
      }

      if (message.type === "error") {
        this.failVoice(message.error || "语音识别失败");
      }
    });

    socketTask.onError((error) => {
      void error;
      this.failVoice("语音连接失败");
    });

    socketTask.onClose((event) => {
      void event;
      if (this.data.voiceMessage && !this.voiceDone) {
        this.failVoice("语音连接已断开");
      }
    });
  },

  sendOrQueueFrame(frameBuffer) {
    if (!this.socketReady || !this.socketTask) {
      this.pendingFrames.push(frameBuffer);
      return;
    }
    this.socketTask.send({
      data: frameBuffer,
      fail: () => this.failVoice("语音发送失败"),
    });
  },

  flushVoiceFrames() {
    while (this.pendingFrames.length && this.socketTask) {
      this.socketTask.send({ data: this.pendingFrames.shift() });
    }
  },

  sendVoiceEndIfReady() {
    if (!this.voiceEnded || this.voiceEndSent || !this.socketReady || !this.socketTask) return;
    this.flushVoiceFrames();
    this.voiceEndSent = true;
    this.socketTask.send({
      data: JSON.stringify({ type: "end" }),
      fail: () => this.failVoice("语音发送失败"),
    });
  },

  async createTodosFromVoice(transcript) {
    if (!transcript) {
      this.failVoice("语音未识别出有效文本");
      return;
    }
    try {
      const result = await api.createTodosFromTranscript(transcript);
      if (!result.items || result.items.length === 0) {
        this.setData({ voiceMessage: result.message || "未添加待办" });
        return;
      }
      this.setData({ voiceMessage: `已添加 ${result.items.length} 项` });
      await this.loadTodos();
    } catch (error) {
      this.failVoice(error.message || "解析失败");
    }
  },

  failVoice(message) {
    this.voiceDone = true;
    this.closeVoiceSocket();
    this.setData({
      recording: false,
      voiceMessage: message,
    });
  },

  closeVoiceSocket() {
    if (this.socketTask) {
      try {
        this.socketTask.close();
      } catch (_error) {
        // ignore
      }
    }
    this.socketTask = null;
  },

  resetVoiceState() {
    this.closeVoiceSocket();
    this.socketReady = false;
    this.recorderStarted = false;
    this.stopRequested = false;
    this.voiceEnded = false;
    this.voiceEndSent = false;
    this.voiceDone = false;
    this.pendingFrames = [];
  },
});
