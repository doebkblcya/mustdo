var api = require("../../utils/api");
var spring = api.spring;
var rubberband = api.rubberband;
var project = api.project;
var VelocityTracker = api.VelocityTracker;

const VIEW_META = {
  today: "今天",
  tomorrow: "明天",
  upcoming: "后续",
};

// How far an item can be swiped left (rpx)
const SWIPE_THRESHOLD = 80;
const MAX_SWIPE = 140;

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

    // Voice
    recording: false,
    voiceMessage: "",
    transcript: "",
    voiceButtonScale: 1,
    voicePanelY: 16,
    voicePanelOpacity: 0,

    // Edit sheet
    editVisible: false,
    sheetTranslateY: 0,
    maskOpacity: 0,
    editTodoId: null,
    editContent: "",
    editDate: "",
    editTime: "",
    editUseTime: false,
    editSubmitting: false,

    // Tab pill
    pillX: 0,
    pillWidth: 0,
  },

  // ---- Animation instances (not in data to avoid setData overhead) ----
  _pillSpring: null,
  _sheetSpring: null,
  _voiceSpring: null,
  _voicePanelSpring: null,
  _maskSpring: null,
  _checkSprings: {},

  // ---- Gesture state ----
  _velocityTracker: new VelocityTracker(),
  _sheetDragState: null,
  _sheetHeight: 0,
  _sheetMeasured: false,
  _tabPositions: null,
  _tabWidth: 0,
  _tabsMeasured: false,
  _swipeState: null,
  _swipeSpring: null,

  // ---- Voice ----
  recorder: null,
  socketTask: null,
  socketReady: false,
  recorderStarted: false,
  stopRequested: false,
  voiceEnded: false,
  voiceEndSent: false,
  voiceDone: false,
  pendingFrames: [],

  // ---- Other ----
  _editCloseTimer: null,

  // ========== Lifecycle ==========

  onLoad() {
    if (!api.getToken()) {
      wx.redirectTo({ url: "/pages/auth/auth" });
      return;
    }
    this.setData({ user: api.getStoredUser() });
    this.setupRecorder();
    this.loadTodos();
    this._measureTabs();
  },

  onUnload() {
    this.closeVoiceSocket();
    this._stopAllSprings();
  },

  onPullDownRefresh() {
    this.loadTodos().finally(() => {
      wx.stopPullDownRefresh();
    });
  },

  // ========== Tab pill ==========

  _measureTabs() {
    setTimeout(() => {
      const query = wx.createSelectorQuery();
      query.selectAll(".tab").boundingClientRect();
      query.select(".tabs").boundingClientRect();
      query.exec((res) => {
        const tabs = res[0];
        const container = res[1];
        if (!tabs || !container || tabs.length < 3) {
          setTimeout(() => this._measureTabs(), 150);
          return;
        }
        this._tabPositions = tabs.map((t) => t.left - container.left);
        this._tabWidth = tabs[0].width;
        this._tabsMeasured = true;

        // Set initial pill position
        const tabIndex = Object.keys(VIEW_META).indexOf(this.data.activeView);
        this.setData({
          pillX: this._tabPositions[tabIndex] || 0,
          pillWidth: this._tabWidth,
        });
      });
    }, 100);
  },

  _animatePill(tabIndex) {
    if (!this._tabsMeasured || !this._tabPositions) return;
    const targetX = this._tabPositions[tabIndex];
    if (this._pillSpring) this._pillSpring.stop();
    this._pillSpring = spring(targetX, {
      damping: 0.8,
      response: 0.3,
      onUpdate: (value) => {
        this.setData({ pillX: value });
      },
    });
  },

  // ========== Data loading ==========

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
      swipeX: 0,
      checkScale: 1,
      deleting: false,
    }));
    this.setData({
      activeView: view,
      viewTitle: VIEW_META[view],
      viewDate: date || "",
      items,
    });
  },

  switchView(event) {
    const view = event.currentTarget.dataset.view;
    this.applyActiveView(view);
    const tabIndex = Object.keys(VIEW_META).indexOf(view);
    this._animatePill(tabIndex);
  },

  // ========== Todo actions ==========

  async toggleTodo(event) {
    const id = Number(event.currentTarget.dataset.id);
    const currentStatus = event.currentTarget.dataset.status;
    const idx = Number(event.currentTarget.dataset.index);
    const newStatus = currentStatus === "done" ? "pending" : "done";

    // Spring check animation
    this._animateCheck(idx, newStatus);

    // Optimistic update
    const items = this.data.items.map((item) =>
      item.id === id ? { ...item, status: newStatus } : item
    );
    this.setData({ items });
    this.patchGroupItem(id, { status: newStatus });

    wx.vibrateShort({ type: "light" });

    try {
      await api.updateTodo(id, { status: newStatus });
    } catch (error) {
      const revertedItems = this.data.items.map((item) =>
        item.id === id ? { ...item, status: currentStatus } : item
      );
      this.setData({ items: revertedItems });
      this.patchGroupItem(id, { status: currentStatus });
      wx.showToast({ title: error.message || "操作失败", icon: "none" });
    }
  },

  _animateCheck(idx, newStatus) {
    const key = String(idx);
    if (this._checkSprings[key]) this._checkSprings[key].stop();

    if (newStatus === "done") {
      // Done: bounce the check circle (momentum feel)
      this._checkSprings[key] = spring(1, {
        damping: 0.7,
        response: 0.25,
        onUpdate: (value) => {
          this.setData({ [`items[${idx}].checkScale`]: value });
        },
      });
    } else {
      // Uncheck: quick settle back
      this._checkSprings[key] = spring(1, {
        damping: 0.9,
        response: 0.2,
        onUpdate: (value) => {
          this.setData({ [`items[${idx}].checkScale`]: value });
        },
      });
    }
  },

  deleteTodo(event) {
    const id = Number(event.currentTarget.dataset.id);
    wx.showModal({
      title: "删除待办",
      content: "确定删除这条待办？",
      success: async (result) => {
        if (!result.confirm) return;

        // Animate out
        const idx = this.data.items.findIndex((item) => item.id === id);
        if (idx >= 0) {
          this.setData({ [`items[${idx}].deleting`]: true });
          await new Promise((r) => setTimeout(r, 260));
        }

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
    this.data.todos = { ...todos, groups };
  },

  // ========== Swipe to delete ==========

  onItemTouchStart(event) {
    // Reset any previous swipe on a different item
    const currentIndex = event.currentTarget.dataset.index;
    this._resetOtherSwipes(currentIndex);

    const touch = event.touches[0];
    this._swipeState = {
      index: currentIndex,
      id: event.currentTarget.dataset.id,
      startX: touch.clientX,
      startY: touch.clientY,
      currentOffset: this.data.items[currentIndex].swipeX || 0,
      swiping: false,
    };
    if (this._swipeSpring) {
      this._swipeSpring.stop();
      this._swipeSpring = null;
    }
  },

  onItemTouchMove(event) {
    if (!this._swipeState) return;
    const s = this._swipeState;
    const touch = event.touches[0];
    const dx = touch.clientX - s.startX;
    const dy = touch.clientY - s.startY;

    // Detect horizontal intent
    if (!s.swiping) {
      if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        s.swiping = true;
      } else {
        return;
      }
    }

    // Only allow left swipe (negative offset)
    let offset = s.currentOffset + dx;
    // Rubber-band past the max
    if (offset < -MAX_SWIPE) {
      const overshoot = -(offset + MAX_SWIPE);
      offset = -MAX_SWIPE - rubberband(overshoot, 200);
    }
    if (offset > 0) {
      offset = rubberband(offset, 200);
    }

    this.setData({ [`items[${s.index}].swipeX`]: offset });
  },

  onItemTouchEnd(event) {
    if (!this._swipeState) return;
    const s = this._swipeState;
    const offset = this.data.items[s.index].swipeX || 0;

    if (s.swiping && offset < -SWIPE_THRESHOLD) {
      // Commit: spring to full reveal
      this._swipeSpring = spring(-MAX_SWIPE, {
        damping: 0.8,
        response: 0.25,
        onUpdate: (value) => {
          this.setData({ [`items[${s.index}].swipeX`]: value });
        },
        onComplete: () => {
          // Auto-delete after a brief pause showing the button
          this._swipeDeleteTimer = setTimeout(() => {
            this._confirmSwipeDelete(s.index, s.id);
          }, 600);
        },
      });
      wx.vibrateShort({ type: "warning" });
    } else {
      // Cancel: spring back to 0
      this._swipeSpring = spring(0, {
        damping: 1.0,
        response: 0.25,
        onUpdate: (value) => {
          this.setData({ [`items[${s.index}].swipeX`]: value });
        },
      });
    }

    this._swipeState = null;
  },

  _resetOtherSwipes(exceptIndex) {
    const items = this.data.items;
    let changed = false;
    for (let i = 0; i < items.length; i++) {
      if (i !== exceptIndex && items[i].swipeX !== 0) {
        items[i] = { ...items[i], swipeX: 0 };
        changed = true;
      }
    }
    if (changed) this.setData({ items });
    if (this._swipeDeleteTimer) {
      clearTimeout(this._swipeDeleteTimer);
      this._swipeDeleteTimer = null;
    }
  },

  _confirmSwipeDelete(index, id) {
    this._swipeDeleteTimer = null;
    // Animate out
    this.setData({ [`items[${index}].deleting`]: true });
    setTimeout(() => {
      const prevItems = this.data.items;
      const prevTodos = this.data.todos;
      this.setData({
        items: prevItems.filter((item) => item.id !== id),
        todos: this.removeFromGroups(prevTodos, id),
      });
      api.deleteTodo(id).catch(() => {
        // Silently fail — item is already removed from UI
      });
    }, 250);
  },

  // ========== Edit sheet ==========

  editTodo(event) {
    const id = Number(event.currentTarget.dataset.id);
    const todo = this.findTodo(id);
    if (!todo) {
      wx.showToast({ title: "待办不存在", icon: "none" });
      return;
    }
    if (this._editCloseTimer) {
      clearTimeout(this._editCloseTimer);
      this._editCloseTimer = null;
    }
    this.setData({
      editVisible: true,
      editTodoId: todo.id,
      editContent: todo.content,
      editDate: todo.due_date,
      editTime: todo.due_time || "09:00",
      editUseTime: Boolean(todo.due_time),
      editSubmitting: false,
    });

    // Measure sheet height after render, then animate in
    this._measureAndOpenSheet();
  },

  _measureAndOpenSheet() {
    // Wait for DOM render
    setTimeout(() => {
      const query = wx.createSelectorQuery();
      query.select(".edit-sheet").boundingClientRect();
      query.exec((res) => {
        const rect = res[0];
        if (rect && rect.height > 0) {
          this._sheetHeight = rect.height;
          this._sheetMeasured = true;
        } else if (!this._sheetMeasured) {
          // Fallback: estimate from screen height
          var windowInfo = wx.getWindowInfo();
          this._sheetHeight = Math.round(windowInfo.windowHeight * 0.55);
        }
        this._animateSheetIn();
      });
    }, 60);
  },

  _animateSheetIn() {
    // Start from below screen
    const startY = this._sheetHeight || 600;
    this.setData({ sheetTranslateY: startY, maskOpacity: 0 });

    if (this._sheetSpring) this._sheetSpring.stop();

    this._sheetSpring = spring(0, {
      damping: 0.8,
      response: 0.3,
      onUpdate: (value) => {
        const progress = 1 - value / startY;
        this.setData({
          sheetTranslateY: value,
          maskOpacity: Math.min(1, Math.max(0, progress)),
        });
      },
    });
  },

  cancelEdit() {
    if (this.data.editSubmitting) return;
    this._animateSheetOut(0);
  },

  _animateSheetOut(initialVelocity) {
    const currentY = this.data.sheetTranslateY;
    const targetY = this._sheetHeight || 600;

    if (this._sheetSpring) this._sheetSpring.stop();

    this._sheetSpring = spring(targetY, {
      damping: 1.0,
      response: 0.25,
      initialVelocity: initialVelocity || 0,
      onUpdate: (value) => {
        const progress = 1 - value / targetY;
        this.setData({
          sheetTranslateY: value,
          maskOpacity: Math.min(1, Math.max(0, progress)),
        });
      },
      onComplete: () => {
        this.setData({ editVisible: false, editTodoId: null, error: "" });
      },
    });
  },

  // ---- Sheet drag gesture ----

  onSheetTouchStart(event) {
    if (this._sheetSpring) {
      this._sheetSpring.stop();
      this._sheetSpring = null;
    }
    const touch = event.touches[0];
    this._velocityTracker.reset(touch.clientY, event.timeStamp);
    this._sheetDragState = {
      startY: touch.clientY,
      startOffset: this.data.sheetTranslateY,
    };
  },

  onSheetTouchMove(event) {
    if (!this._sheetDragState) return;
    const touch = event.touches[0];
    const s = this._sheetDragState;
    const dy = touch.clientY - s.startY;

    this._velocityTracker.addPoint(touch.clientY, event.timeStamp);

    let newY = s.startOffset + dy;

    // Rubber-band when pulling up past 0 (overscroll)
    if (newY < 0) {
      newY = -rubberband(-newY, this._sheetHeight || 600);
    }

    // Allow pulling down freely (closing direction)
    const progress = 1 - newY / (this._sheetHeight || 600);
    this.setData({
      sheetTranslateY: newY,
      maskOpacity: Math.min(1, Math.max(0, progress)),
    });
  },

  onSheetTouchEnd(event) {
    if (!this._sheetDragState) return;
    const s = this._sheetDragState;
    this._sheetDragState = null;

    const currentY = this.data.sheetTranslateY;
    const velocity = this._velocityTracker.velocity();
    const sheetH = this._sheetHeight || 600;

    // Project momentum
    const projectedY = currentY + project(velocity, 0.997);
    const threshold = sheetH * 0.3;

    if (projectedY > threshold || velocity > 200) {
      // Dismiss — hand off velocity
      this._animateSheetOut(velocity);
      wx.vibrateShort({ type: "light" });
    } else {
      // Snap back
      this._sheetSpring = spring(0, {
        damping: 0.8,
        response: 0.3,
        initialVelocity: velocity,
        onUpdate: (value) => {
          const progress = 1 - value / sheetH;
          this.setData({
            sheetTranslateY: value,
            maskOpacity: Math.min(1, Math.max(0, progress)),
          });
        },
      });
    }
  },

  noop() {},

  // ---- Edit form ----

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

      const items = ((todos && todos.groups && todos.groups[this.data.activeView]) || []).map((item) => ({
        ...item,
        meta: `${item.due_date}${item.due_time ? ` ${item.due_time}` : ""}`,
        swipeX: 0,
        checkScale: 1,
        deleting: false,
      }));

      this.setData({ editSubmitting: false, todos, items });

      wx.vibrateShort({ type: "light" });
      this._animateSheetOut(0);
    } catch (error) {
      wx.showToast({ title: error.message || "保存失败", icon: "none" });
      this.setData({ editSubmitting: false });
    }
  },

  // ========== Voice input ==========

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
      this._animateVoicePanel(true);
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

    // Spring press animation
    if (this._voiceSpring) this._voiceSpring.stop();
    this._voiceSpring = spring(0.97, {
      damping: 0.8,
      response: 0.15,
      onUpdate: (value) => {
        this.setData({ voiceButtonScale: value });
      },
    });

    wx.vibrateShort({ type: "heavy" });

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

    // Spring release animation
    if (this._voiceSpring) this._voiceSpring.stop();
    this._voiceSpring = spring(1, {
      damping: 0.9,
      response: 0.2,
      onUpdate: (value) => {
        this.setData({ voiceButtonScale: value });
      },
    });

    this._animateVoicePanel(false);
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

  _animateVoicePanel(show) {
    if (this._voicePanelSpring) this._voicePanelSpring.stop();
    if (show) {
      this._voicePanelSpring = spring(1, {
        damping: 0.8,
        response: 0.3,
        onUpdate: (value) => {
          this.setData({
            voicePanelY: (1 - value) * 16,
            voicePanelOpacity: value,
          });
        },
      });
    } else {
      this._voicePanelSpring = spring(0, {
        damping: 1.0,
        response: 0.2,
        onUpdate: (value) => {
          this.setData({
            voicePanelOpacity: value,
          });
        },
      });
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
        wx.vibrateShort({ type: "light" });
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
      // Re-measure tabs after reload
      setTimeout(() => this._measureTabs(), 200);
    } catch (error) {
      this.failVoice(error.message || "解析失败");
    }
  },

  failVoice(message) {
    this.voiceDone = true;
    this.closeVoiceSocket();

    if (this._voiceSpring) this._voiceSpring.stop();
    this._voiceSpring = spring(1, {
      damping: 0.9,
      response: 0.2,
      onUpdate: (value) => {
        this.setData({ voiceButtonScale: value });
      },
    });

    this.setData({
      recording: false,
      voiceMessage: message,
    });

    setTimeout(() => {
      this._animateVoicePanel(false);
    }, 1500);
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

  // ========== Cleanup ==========

  _stopAllSprings() {
    const springs = [
      this._pillSpring, this._sheetSpring, this._voiceSpring,
      this._voicePanelSpring, this._maskSpring, this._swipeSpring,
    ];
    springs.forEach((s) => { if (s) s.stop(); });
    Object.values(this._checkSprings).forEach((s) => { if (s) s.stop(); });
  },
});
