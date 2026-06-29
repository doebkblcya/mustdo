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
    voiceDebug: "",
    transcript: "",
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
  frameCount: 0,
  audioBytes: 0,

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

    this.recorder.onStart(() => {
      console.log("recorder start");
      this.recorderStarted = true;
      this.updateVoiceDebug("recorder=started");
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
      const byteLength = event.frameBuffer ? event.frameBuffer.byteLength : 0;
      console.log("voice frame bytes", byteLength);
      if (event.frameBuffer) {
        this.frameCount += 1;
        this.audioBytes += byteLength;
        this.updateVoiceDebug();
        this.sendOrQueueFrame(event.frameBuffer);
      }
    });

    this.recorder.onStop(() => {
      console.log("recorder stop");
      this.recorderStarted = false;
      this.voiceEnded = true;
      this.updateVoiceDebug("recorder=stopped");
      this.sendVoiceEndIfReady();
    });

    this.recorder.onError((error) => {
      console.error("recorder error", error);
      this.recorderStarted = false;
      this.updateVoiceDebug("recorder=error");
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
      voiceDebug: "socket=连接中 recorder=启动中 frames=0 bytes=0",
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
        encodeBitRate: 256000,
        format: "PCM",
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
      console.log("recorder stop skipped: not started");
      return;
    }
    try {
      this.recorder.stop();
    } catch (error) {
      console.warn("recorder stop failed", error);
      this.recorderStarted = false;
    }
  },

  bindVoiceSocket(socketTask) {
    socketTask.onOpen(() => {
      console.log("voice socket open");
      this.updateVoiceDebug("socket=open");
    });

    socketTask.onMessage((event) => {
      console.log("voice socket message", event.data);
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_error) {
        this.failVoice("语音服务返回格式异常");
        return;
      }

      if (message.type === "ready") {
        this.socketReady = true;
        this.updateVoiceDebug("socket=ready");
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
      console.error("voice socket error", error);
      this.updateVoiceDebug("socket=error");
      this.failVoice("语音连接失败");
    });

    socketTask.onClose((event) => {
      console.log("voice socket close", event);
      this.updateVoiceDebug("socket=closed");
      if (this.data.voiceMessage && !this.voiceDone && !this.voiceEndSent) {
        this.failVoice("语音连接已断开");
      }
    });
  },

  sendOrQueueFrame(frameBuffer) {
    if (!this.socketReady || !this.socketTask) {
      this.pendingFrames.push(frameBuffer);
      this.updateVoiceDebug("frame=queued");
      return;
    }
    this.socketTask.send({
      data: frameBuffer,
      success: () => this.updateVoiceDebug("frame=sent"),
      fail: (error) => {
        console.error("send frame failed", error);
        this.updateVoiceDebug("frame=send_failed");
      },
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
      success: () => this.updateVoiceDebug("end=sent"),
      fail: (error) => {
        console.error("send end failed", error);
        this.updateVoiceDebug("end=send_failed");
      },
    });
  },

  updateVoiceDebug(extra) {
    const parts = [
      `socket=${this.socketReady ? "ready" : this.socketTask ? "open" : "none"}`,
      `recorder=${this.recorderStarted ? "started" : "stopped"}`,
      `frames=${this.frameCount}`,
      `bytes=${this.audioBytes}`,
      `queued=${this.pendingFrames.length}`,
    ];
    if (extra) parts.push(extra);
    this.setData({ voiceDebug: parts.join(" ") });
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
    this.frameCount = 0;
    this.audioBytes = 0;
  },
});
