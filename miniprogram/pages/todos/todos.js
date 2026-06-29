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
    items: [],
    todos: null,
    loading: false,
    error: "",
    recording: false,
    voiceMessage: "",
    transcript: "",
  },

  recorder: null,
  socketTask: null,
  socketReady: false,
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

  async loadTodos() {
    this.setData({ loading: true, error: "" });
    try {
      const todos = await api.listTodos();
      this.setData({ todos, loading: false });
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
    try {
      await api.updateTodo(id, { status: currentStatus === "done" ? "pending" : "done" });
      await this.loadTodos();
    } catch (error) {
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
        try {
          await api.deleteTodo(id);
          await this.loadTodos();
        } catch (error) {
          wx.showToast({ title: error.message || "删除失败", icon: "none" });
        }
      },
    });
  },

  async logout() {
    await api.logout();
    wx.redirectTo({ url: "/pages/auth/auth" });
  },

  setupRecorder() {
    if (this.recorder) return;
    this.recorder = wx.getRecorderManager();

    this.recorder.onFrameRecorded((event) => {
      if (event.frameBuffer) {
        this.sendOrQueueFrame(event.frameBuffer);
      }
    });

    this.recorder.onStop(() => {
      this.voiceEnded = true;
      this.sendVoiceEndIfReady();
    });

    this.recorder.onError((error) => {
      this.failVoice(error.errMsg || "录音失败");
    });
  },

  startVoice() {
    if (this.data.recording) return;
    if (!api.getToken()) {
      wx.redirectTo({ url: "/pages/auth/auth" });
      return;
    }

    this.resetVoiceState();
    this.setData({
      recording: true,
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

    this.recorder.start({
      duration: 30000,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 256000,
      format: "PCM",
      frameSize: 4,
    });
  },

  stopVoice() {
    if (!this.data.recording) return;
    this.setData({ recording: false, voiceMessage: "正在等待最终文本" });
    this.voiceEnded = true;
    try {
      this.recorder.stop();
    } catch (_error) {
      this.sendVoiceEndIfReady();
    }
  },

  bindVoiceSocket(socketTask) {
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

    socketTask.onError(() => {
      this.failVoice("语音连接失败");
    });

    socketTask.onClose(() => {
      if (this.data.voiceMessage && !this.voiceDone && !this.voiceEndSent) {
        this.failVoice("语音连接已断开");
      }
    });
  },

  sendOrQueueFrame(frameBuffer) {
    if (!this.socketReady || !this.socketTask) {
      this.pendingFrames.push(frameBuffer);
      return;
    }
    this.socketTask.send({ data: frameBuffer });
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
    this.socketTask.send({ data: JSON.stringify({ type: "end" }) });
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
    this.voiceEnded = false;
    this.voiceEndSent = false;
    this.voiceDone = false;
    this.pendingFrames = [];
  },
});
