var config = require("../../config");
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

// Display preference — hide/show completed items (persisted locally)
const SHOW_COMPLETED_KEY = "mustdo_show_completed";

// AI 动态整理（今天视图）缓存：{fingerprint, groups}
const ORGANIZE_CACHE_KEY = "mustdo_organize_today";

// "2026-08-20" → "8月20日"
function formatDateCN(dateStr) {
  if (!dateStr) return "";
  const parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  return parseInt(parts[1], 10) + "月" + parseInt(parts[2], 10) + "日";
}

// ---- Reminder time helpers ----

function pad2(n) {
  return n < 10 ? "0" + n : "" + n;
}

// "2026-08-25" + "14:30" → local Date
function dateTimeToDate(dateStr, timeStr) {
  const [y, mo, d] = dateStr.split("-").map(Number);
  const [h, mi] = timeStr.split(":").map(Number);
  return new Date(y, mo - 1, d, h, mi, 0);
}

function toDateStr(d) {
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
}

function toTimeStr(d) {
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
}

// local Date → "2026-08-25T14:30:00+08:00"（后端按 Asia/Shanghai 解析）
function toIsoLocal(d) {
  return toDateStr(d) + "T" + toTimeStr(d) + ":00+08:00";
}

// "2026-08-25T14:30:00+08:00" → Date（带偏移安全解析）
function parseIso(isoStr) {
  const m = isoStr.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(?:([+-])(\d{2}):(\d{2}))?/);
  if (!m) return null;
  let ms = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
  if (m[7] && m[8]) {
    const offsetMin = (+m[8]) * 60 + (+m[9] || 0);
    ms -= (m[7] === "+" ? 1 : -1) * offsetMin * 60000;
  }
  return new Date(ms);
}

// 提醒预设（分钟偏移）。默认选中「准时提醒」；
// 某档位提醒时间已过去（剩余时间不足）→ 不可选并提示，不允许创建。
const REMIND_PRESETS = [
  { label: "准时提醒", minutesBefore: 0 },
  { label: "提前 10 分钟", minutesBefore: 10 },
  { label: "提前 30 分钟", minutesBefore: 30 },
  { label: "提前 1 小时", minutesBefore: 60 },
];
const REMIND_CUSTOM_INDEX = REMIND_PRESETS.length; // 自定义选项下标

// Swipe-to-reveal
const SWIPE_ZONE = 80; // px — pin / delete zone width
const SWIPE_THRESHOLD = 40; // px — commit threshold

// Local sort key (mirrors backend _todo_sort_key)
function _todoSort(a, b) {
  // Pinned first
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
  // Pending before done
  if (a.status !== b.status) return a.status === 'pending' ? -1 : 1;
  // Has-time before no-time
  var aHasTime = !!a.due_time;
  var bHasTime = !!b.due_time;
  if (aHasTime !== bHasTime) return aHasTime ? -1 : 1;
  // By time
  var aTime = a.due_time || '';
  var bTime = b.due_time || '';
  if (aTime !== bTime) return aTime < bTime ? -1 : 1;
  // By id
  return a.id - b.id;
}


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
    showCompleted: true, // hide/show completed items — read from storage in onLoad

    // AI organize (today view)
    organizeMode: false, // 当前是否展示 AI 分组视图
    organizing: false,   // 正在请求后端整理
    organizeError: "",
    organizeGroups: [],  // [{name, todo_ids}] 缓存结构
    todayHasPending: false, // 今天是否有未完成项（决定入口显示）

    // Voice recording + unified processing panel
    recording: false,
    panelActive: false,
    voiceCancelHover: false,

    // Composer bar (keyboard ⇄ voice)
    composerMode: "voice", // default: hold-to-talk; toggle switches to text input
    composerText: "",
    composerCursor: -1,
    composerFocus: false,
    composerSubmitting: false,
    composerPlaceholder: "输入文字",
    composerLift: 0, // px — lift above keyboard
    isIOS: false,    // iOS uses keyboard confirm key, no in-bar send arrow

    // Long-text composer. Compact/expanded native nodes share text and cursor state.
    expandVisible: false,
    expanded: false,
    composerOverflow: false,
    composerTall: false,
    composerKeyboardHeight: 0,
    expandTop: 0,

    // Edit sheet
    editVisible: false,
    sheetTranslateY: 0,
    maskOpacity: 0,
    sheetMode: "edit", // 'edit' | 'reminder' —— 共用同一张底部弹层
    editTodoId: null,
    editContent: "",
    editDate: "",
    editTime: "",
    editUseTime: false,
    editSubmitting: false,

    // Reminder sheet
    remindTodoId: null,
    remindTodoContent: "",
    remindTodoDue: "",
    remindOptions: [],
    remindSelected: 0,
    remindCustomDate: "",
    remindCustomTime: "",
    remindSubmitting: false,
    remindHasActive: false,

    // Tab pill
    pillX: 0,
    pillWidth: 0,

    // Calendar (expandable on 后续 tab)
    calendarVisible: false,
    calHeight: 0,
    calTitle: "",
    calYear: null,
    calMonth: null,
    calendarWeeks: [],
    selectedDate: "",
    upcomingLabel: "后续",
  },

  // ---- Animation instances (not in data to avoid setData overhead) ----
  _pillSpring: null,
  _sheetSpring: null,
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
  _calSpring: null,

  // ---- Voice ----
  recorder: null,
  recorderStarted: false,
  _voicePermissionPending: false,
  _voiceTouchStartY: 0,

  // ---- Other ----
  _editCloseTimer: null,
  _composerSwitchTimer: null,
  _composerSwitching: false,

  // ========== Lifecycle ==========

  onLoad(options) {
    if (!api.getToken()) {
      wx.redirectTo({ url: "/pages/auth/auth" });
      return;
    }
    this.setData({
      user: api.getStoredUser(),
      // First launch defaults to showing completed items (undefined → true)
      showCompleted: wx.getStorageSync(SHOW_COMPLETED_KEY) !== false,
    });
    this.setupRecorder();

    // iOS keeps the send action on the keyboard confirm key (no in-bar arrow)
    const device = wx.getDeviceInfo ? wx.getDeviceInfo() : wx.getSystemInfoSync();
    const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    this.setData({
      isIOS: device.platform === "ios",
      expandTop: Math.round(windowInfo.windowHeight * 0.2),
    });

    // Pin the compact bar above the keyboard. In expanded mode the same height
    // becomes the panel's bottom inset, keeping its top visible on small screens.
    if (wx.onKeyboardHeightChange) {
      this._keyboardHeightHandler = (res) => {
        const height = Math.max(0, Number(res.height) || 0);
        this.setData({
          composerKeyboardHeight: height,
          composerLift: height > 0 ? -height : 0,
        });
      };
      wx.onKeyboardHeightChange(this._keyboardHeightHandler);
    }

    this.loadTodos();
    this._measureTabs();
  },

  // 从垃圾桶返回：恢复/移到今天可能改变主列表，按需刷新（openTrash 时置标记）
  onShow() {
    if (this._fromTrash) {
      this._fromTrash = false;
      this.loadTodos();
    }
  },

  onUnload() {
    if (wx.offKeyboardHeightChange && this._keyboardHeightHandler) {
      wx.offKeyboardHeightChange(this._keyboardHeightHandler);
    }
    if (this._composerSwitchTimer) clearTimeout(this._composerSwitchTimer);
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
      this._syncTodayState();
      this._buildCalendar();
      if (this.data.selectedDate) {
        this.applyDateFilter(this.data.selectedDate);
      }
      this._syncUpcomingLabel();
    } catch (error) {
      if (error.statusCode === 401) {
        api.clearSession();
        wx.redirectTo({ url: "/pages/auth/auth" });
        return;
      }
      this.setData({ loading: false, error: error.message || "加载失败" });
    }
  },

  // Render-layer filter: hide completed items without touching todos.groups
  _filterVisible(items) {
    if (this.data.showCompleted) return items;
    return items.filter((item) => item.status !== "done");
  },

  // Rebuild the current view from todos.groups (respects visibility + date filter)
  _renderCurrentView() {
    if (this.data.selectedDate) {
      this.applyDateFilter(this.data.selectedDate);
    } else {
      this.applyActiveView(this.data.activeView);
    }
  },

  toggleShowCompleted() {
    const next = !this.data.showCompleted;
    this.setData({ showCompleted: next });
    wx.setStorageSync(SHOW_COMPLETED_KEY, next);
    this._renderCurrentView();
  },

  // 垃圾桶入口（v2-04）：纯入口，无数量提示；返回时 onShow 按需刷新
  openTrash() {
    this._fromTrash = true;
    wx.navigateTo({ url: "/pages/trash/trash" });
  },

  openSettings() {
    wx.navigateTo({ url: "/pages/settings/settings" });
  },

  // ========== AI 动态整理（今天视图） ==========

  // 今天未完成项的指纹：日期 + 每个待办的 id/content/due_time/pinned/status
  _organizeFingerprint(pendingItems) {
    const today = this.data.todayDate || "";
    const parts = pendingItems
      .map((t) => `${t.id}:${t.content}:${t.due_time || ""}:${t.pinned ? 1 : 0}:${t.status}`)
      .join("|");
    const s = today + "|" + parts;
    let h = 5381;
    for (let i = 0; i < s.length; i++) {
      h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    }
    return (h >>> 0).toString(36);
  },

  _todayPendingItems() {
    const groups = this.data.todos && this.data.todos.groups ? this.data.todos.groups : {};
    return (groups.today || []).filter((t) => t.status === "pending");
  },

  toggleOrganize() {
    if (this.data.organizing) return;
    if (!this.data.organizeMode) {
      this._enterOrganize();
    } else {
      // 已在 AI 视图：再次点击 = 手动重新整理（把未分组任务一并纳入）
      this._requestOrganize();
    }
  },

  onOrganizeDefaultTap() {
    if (this.data.organizing) return;
    if (!this.data.organizeMode) return;
    this.setData({ organizeMode: false, organizeError: "" });
    this._renderCurrentView();
  },

  _enterOrganize() {
    const pending = this._todayPendingItems();
    if (!pending.length) return;
    const fingerprint = this._organizeFingerprint(pending);
    const cached = wx.getStorageSync(ORGANIZE_CACHE_KEY);
    if (cached && cached.fingerprint === fingerprint && Array.isArray(cached.groups)) {
      // 任务集合未变化：直接复用缓存
      this.setData({ organizeMode: true, organizeGroups: cached.groups, organizeError: "" });
      this.applyActiveView(this.data.activeView);
      return;
    }
    this._requestOrganize(fingerprint);
  },

  _requestOrganize(fingerprint) {
    const pending = this._todayPendingItems();
    if (!pending.length) return;
    const fp = fingerprint || this._organizeFingerprint(pending);
    this.setData({ organizeMode: true, organizing: true, organizeError: "" });
    api.organizeTodos({
      view: "today",
      items: pending.map((t) => ({ id: t.id, content: t.content, due_time: t.due_time })),
    })
      .then((res) => {
        const groups = (res && res.groups) || [];
        wx.setStorageSync(ORGANIZE_CACHE_KEY, { fingerprint: fp, groups });
        this.setData({ organizing: false, organizeGroups: groups });
        this.applyActiveView(this.data.activeView);
      })
      .catch((err) => {
        // 失败：提示后自动切回默认视图
        this.setData({ organizing: false, organizeMode: false, organizeGroups: [] });
        this._renderCurrentView();
        wx.showToast({ title: err.message || "AI 整理失败", icon: "none" });
      });
  },

  // AI 分组视图渲染：组标题行 + 组内卡片；未分组任务（整理后新增）单独成区
  _renderOrganizeItems(patch) {
    const groups = this.data.todos && this.data.todos.groups ? this.data.todos.groups : {};
    const base = (groups.today || []).map((item) => ({
      ...item,
      pinned: Boolean(item.pinned),
      meta: `${item.due_date}${item.due_time ? ` ${item.due_time}` : ""}`,
      checkScale: 1,
      deleting: false,
      key: item.id,
    }));
    const visible = this._filterVisible(base);
    if (!visible.length) {
      // 组内全部清空（含隐藏偏好）→ 自动回到默认视图
      this.setData({ ...(patch || {}), organizeMode: false, organizeGroups: [], items: [] });
      return;
    }
    const org = this.data.organizeGroups || [];
    const groupedIds = {};
    org.forEach((g) => (g.todo_ids || []).forEach((id) => { groupedIds[id] = true; }));
    const items = [];
    org.forEach((g) => {
      const members = visible
        .filter((t) => (g.todo_ids || []).indexOf(t.id) !== -1)
        .sort(_todoSort);
      if (members.length) {
        items.push({ __header: true, name: g.name, key: "h-" + items.length });
        items.push(...members);
      }
    });
    const ungrouped = visible.filter((t) => !groupedIds[t.id]);
    if (ungrouped.length) {
      items.push({ __header: true, name: "未分组", key: "h-" + items.length });
      items.push(...ungrouped.sort(_todoSort));
    }
    this.setData({ ...(patch || {}), items });
  },

  _refreshTodayHasPending() {
    const groups = this.data.todos && this.data.todos.groups ? this.data.todos.groups : {};
    this.setData({ todayHasPending: (groups.today || []).some((t) => t.status === "pending") });
  },

  // 今天待办集合变化后的统一刷新：入口可见性 + AI 视图清空时回默认
  _syncTodayState() {
    this._refreshTodayHasPending();
    if (this.data.organizeMode && !this.data.todayHasPending) {
      this.setData({ organizeMode: false, organizeGroups: [] });
      this._renderCurrentView();
    }
  },

  applyActiveView(view) {
    const todos = this.data.todos;
    const groups = todos && todos.groups ? todos.groups : {};
    const date = view === "today" ? todos && todos.today_date : view === "tomorrow" ? todos && todos.tomorrow_date : "";
    const patch = {
      activeView: view,
      viewTitle: VIEW_META[view],
      viewDate: date || "",
    };
    if (this.data.organizeMode && view === "today") {
      this._renderOrganizeItems(patch);
      return;
    }
    const items = this._filterVisible(
      (groups[view] || []).map((item) => ({
        ...item,
        pinned: Boolean(item.pinned),
        meta: `${item.due_date}${item.due_time ? ` ${item.due_time}` : ""}`,
        checkScale: 1,
        deleting: false,
        key: item.id,
      }))
    );
    this.setData({ ...patch, items });
  },

  switchView(event) {
    const view = event.currentTarget.dataset.view;
    if (view === this.data.activeView) {
      // Re-tap the active tab (upcoming): the tab label IS the next action
      if (view === "upcoming") {
        if (this.data.selectedDate && !this.data.calendarVisible) {
          this._expandCalendar(); // 「8月20日」→ 展开，文案变「查看全部」
        } else if (this.data.selectedDate) {
          this.clearDateFilter(); // 「查看全部」→ 清空并收起
        } else if (this.data.calendarVisible) {
          this._collapseCalendar(); // 「收起日历」
        } else {
          this._expandCalendar(); // 「展开日历」
        }
      }
      return;
    }
    // Switching to another tab — collapse calendar & clear date filter
    this._collapseCalendar();
    this.setData({ selectedDate: "" });
    this.applyActiveView(view);
    const tabIndex = Object.keys(VIEW_META).indexOf(view);
    this._animatePill(tabIndex);
    this._syncUpcomingLabel();
  },

  // 后续 tab 文案 = 状态机，永远显示下一步动作：
  // 今天/明天 → 后续 · 展开日历 ⇄ 收起日历 · 8月20日 ⇄ 查看全部
  _syncUpcomingLabel() {
    const { activeView, calendarVisible, selectedDate } = this.data;
    let label = "后续";
    if (activeView === "upcoming") {
      if (selectedDate) {
        label = calendarVisible ? "查看全部" : formatDateCN(selectedDate);
      } else {
        label = calendarVisible ? "收起日历" : "展开日历";
      }
    }
    this.setData({ upcomingLabel: label });
  },

  // ========== Calendar (后续 tab) ==========

  _expandCalendar() {
    if (this.data.calendarVisible) return;
    this._buildCalendar(); // 展开时重建网格：选中标记/圆点跟随最新状态，避免脏高亮残留
    this.setData({ calendarVisible: true });
    this._syncUpcomingLabel(); // → 收起日历 / 查看全部
    this._fitCalendarHeight();
  },

  // Re-measure the calendar card and spring the wrapper height to match
  _fitCalendarHeight() {
    var self = this;
    setTimeout(function() {
      const query = wx.createSelectorQuery();
      query.select(".calendar").boundingClientRect();
      query.exec(function(res) {
        const rect = res && res[0];
        const target = (rect && rect.height) || 320;
        if (self._calSpring) self._calSpring.stop();
        self._calSpring = spring(target, {
          damping: 0.8,
          response: 0.32,
          onUpdate: function(value) {
            self.setData({ calHeight: value });
          },
        });
      });
    }, 80);
  },

  _collapseCalendar() {
    if (!this.data.calendarVisible) return;
    if (this._calSpring) this._calSpring.stop();
    var self = this;
    this._calSpring = spring(0, {
      damping: 0.9,
      response: 0.26,
      onUpdate: function(value) {
        self.setData({ calHeight: value });
      },
      onComplete: function() {
        self.setData({ calendarVisible: false, calHeight: 0 });
        self._syncUpcomingLabel(); // → 展开日历 / 8月20日
      },
    });
  },

  // Date set of days (>= today) that still have pending todos → dot marks
  _collectDotDates() {
    const todos = this.data.todos;
    const groups = todos && todos.groups ? todos.groups : {};
    const today = this.data.todayDate || "";
    const set = {};
    for (const key of ["today", "tomorrow", "upcoming"]) {
      for (const item of groups[key] || []) {
        if (item.status === "pending" && item.due_date && (!today || item.due_date >= today)) {
          set[item.due_date] = true;
        }
      }
    }
    return set;
  },

  // Build the 6×7 grid for calYear/calMonth (Monday-first), default = current month
  _buildCalendar() {
    const today = this.data.todayDate || "";
    if (!today) return;

    let year = this.data.calYear;
    let month = this.data.calMonth;
    if (!year) {
      const parts = today.split("-").map(Number);
      year = parts[0];
      month = parts[1] - 1; // 0-based
    }

    const dotSet = this._collectDotDates();
    const lead = (new Date(year, month, 1).getDay() + 6) % 7; // Monday-first offset
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const selected = this.data.selectedDate;

    const cells = [];
    for (let i = 0; i < 42; i++) {
      const dayNum = i - lead + 1;
      const inMonth = dayNum >= 1 && dayNum <= daysInMonth;
      if (!inMonth) {
        cells.push({ key: "c" + i, dateStr: "", day: 0, inMonth: false, beforeToday: false, hasDot: false, isSelected: false });
        continue;
      }
      const mm = month + 1 < 10 ? "0" + (month + 1) : "" + (month + 1);
      const dd = dayNum < 10 ? "0" + dayNum : "" + dayNum;
      const dateStr = year + "-" + mm + "-" + dd;
      const beforeToday = dateStr < today;
      cells.push({
        key: "c" + i,
        dateStr: dateStr,
        day: dayNum,
        inMonth: true,
        beforeToday: beforeToday,
        hasDot: !beforeToday && !!dotSet[dateStr],
        isSelected: dateStr === selected,
      });
    }

    const weeks = [];
    for (let w = 0; w < 6; w++) {
      weeks.push({ weekIndex: "w" + w, days: cells.slice(w * 7, w * 7 + 7) });
    }

    this.setData({
      calYear: year,
      calMonth: month,
      calTitle: year + "年" + (month + 1) + "月",
      calendarWeeks: weeks,
    });
  },

  shiftCalendarMonth(event) {
    const delta = Number(event.currentTarget.dataset.delta);
    let month = this.data.calMonth + delta;
    let year = this.data.calYear;
    if (month < 0) { month = 11; year -= 1; }
    if (month > 11) { month = 0; year += 1; }
    this.setData({ calMonth: month, calYear: year });
    this._buildCalendar();
  },

  onCalDayTap(event) {
    const ds = event.currentTarget.dataset;
    const date = ds.date;
    if (!ds.inmonth || ds.before || !date) return;
    const today = this.data.todayDate;
    const tomorrow = this.data.todos && this.data.todos.tomorrow_date;
    // 今天/明天 → 跳到对应 tab，并清掉选中的日期
    if (date === today || (tomorrow && date === tomorrow)) {
      const view = date === today ? "today" : "tomorrow";
      this.setData({ selectedDate: "" });
      this._collapseCalendar();
      this.applyActiveView(view);
      this._animatePill(Object.keys(VIEW_META).indexOf(view));
      this._syncUpcomingLabel();
      return;
    }
    this.setData({ selectedDate: date });
    this._buildCalendar();
    this.applyDateFilter(date);
    this._collapseCalendar(); // 选完日期收起（标签在收起动画完成后变日期）
  },

  applyDateFilter(dateStr) {
    const todos = this.data.todos;
    const groups = todos && todos.groups ? todos.groups : {};
    const all = [].concat(groups.today || [], groups.tomorrow || [], groups.upcoming || []);
    const items = this._filterVisible(
      all
        .filter((t) => t.due_date === dateStr)
        .map((item) => ({
          ...item,
          pinned: Boolean(item.pinned),
          meta: `${item.due_date}${item.due_time ? ` ${item.due_time}` : ""}`,
          checkScale: 1,
          deleting: false,
          key: item.id,
        }))
    ).sort(_todoSort);
    this.setData({ items, viewTitle: formatDateCN(dateStr), viewDate: dateStr });
  },

  clearDateFilter() {
    this.setData({ selectedDate: "" });
    this._buildCalendar();
    this.applyActiveView(this.data.activeView);
    this._collapseCalendar(); // 查看全部后收起日历（标签在收起动画完成后同步）
  },

  // ========== Todo actions ==========

  // 一键移到明天：乐观移组 → PATCH due_date → 失败按 ID 回滚到原分组原位置
  moveToTomorrow(event) {
    const id = Number(event.currentTarget.dataset.id);
    const todos = this.data.todos;
    if (!todos || !todos.groups) return;
    const tomorrow = todos.tomorrow_date;
    if (!tomorrow) return;

    // Locate the item in the today group (only today's pending items can move)
    let fromGroup = "today";
    let fromIndex = -1;
    let item = null;
    const todayGroup = todos.groups.today || [];
    fromIndex = todayGroup.findIndex((t) => t.id === id);
    item = fromIndex !== -1 ? todayGroup[fromIndex] : null;
    if (!item || item.status !== "pending") return;

    // Optimistic: leave source group → join tomorrow (content/time/pinned kept,
    // reminder 由后端因改期联动取消，本地同步清掉)
    const groups = { ...todos.groups };
    groups[fromGroup] = groups[fromGroup].filter((t) => t.id !== id);
    groups.tomorrow = (groups.tomorrow || [])
      .concat({ ...item, due_date: tomorrow, reminder: null })
      .sort(_todoSort);
    this.data.todos = { ...todos, groups };

    // Leave the rendered list (entry is only on the today view)
    this.setData({ items: this.data.items.filter((t) => t.id !== id) });
    this._buildCalendar(); // dot marks follow pending items
    this._syncTodayState(); // entry visibility + auto-leave organize when empty
    // 组织视图：重建 AI 分组，空组标题自动消失
    if (this.data.organizeMode) this._renderOrganizeItems();

    wx.vibrateShort({ type: "light" });

    api
      .updateTodo(id, { due_date: tomorrow })
      .then(() => {
        wx.showToast({ title: "已移到明天", icon: "none" });
      })
      .catch((err) => {
        // Roll back by id — restore original group & position
        const groups2 = { ...this.data.todos.groups };
        groups2.tomorrow = groups2.tomorrow.filter((t) => t.id !== id);
        const restored = [...(groups2[fromGroup] || [])];
        restored.splice(Math.min(fromIndex, restored.length), 0, item);
        groups2[fromGroup] = restored;
        this.data.todos = { ...this.data.todos, groups: groups2 };
        this._renderCurrentView();
        this._buildCalendar();
        wx.showToast({ title: err.message || "操作失败", icon: "none" });
      });
  },

  async toggleTodo(event) {
    const id = Number(event.currentTarget.dataset.id);
    const currentStatus = event.currentTarget.dataset.status;
    const idx = Number(event.currentTarget.dataset.index);
    const newStatus = currentStatus === "done" ? "pending" : "done";
    const prev = this.findTodo(id);
    const prevReminder = prev ? prev.reminder : null;
    // 完成待办 → 后端联动取消提醒，本地同步清掉
    const clearReminder = newStatus === "done";

    // Spring check animation
    this._animateCheck(idx, newStatus);

    // Optimistic update
    const items = this.data.items.map((item) =>
      item.id === id
        ? { ...item, status: newStatus, reminder: clearReminder ? null : item.reminder }
        : item
    );
    this.setData({ items });
    this.patchGroupItem(id, { status: newStatus, reminder: clearReminder ? null : prevReminder });
    this._buildCalendar(); // pending ⇄ done changes the dot marks
    this._syncTodayState(); // entry visibility + auto-leave organize when empty

    wx.vibrateShort({ type: "light" });

    try {
      await api.updateTodo(id, { status: newStatus });
      // Hidden-completed mode: let the check bounce finish, then drop the item
      if (newStatus === "done" && !this.data.showCompleted) {
        setTimeout(() => {
          // Skip if the preference was switched back to showing in the meantime
          if (this.data.showCompleted) return;
          const item = this.data.items.find((i) => i.id === id);
          if (item && item.status === "done") {
            if (this.data.organizeMode) {
              // Rebuild the organize view (drops empty group headers, recomputes 未分组)
              this._renderOrganizeItems();
            } else {
              this.setData({ items: this.data.items.filter((i) => i.id !== id) });
            }
          }
        }, 380);
      }
    } catch (error) {
      this.patchGroupItem(id, { status: currentStatus, reminder: prevReminder });
      // Rebuild the view — restores the item if it was already removed
      this._renderCurrentView();
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

  // ========== Item swipe (right=pin, left=delete) ==========

  onItemTouchStart(event) {
    const index = event.currentTarget.dataset.index;
    this._closeOtherSwipes(index);

    if (this._swipeSpring) {
      this._swipeSpring.stop();
      this._swipeSpring = null;
    }

    const touch = event.touches[0];
    this._swipeState = {
      index,
      startX: touch.clientX,
      startY: touch.clientY,
      currentOffset: this.data.items[index].swipeX || 0,
      swiping: false,
    };
  },

  onItemTouchMove(event) {
    if (!this._swipeState) return;
    const s = this._swipeState;
    const touch = event.touches[0];
    const dx = touch.clientX - s.startX;
    const dy = touch.clientY - s.startY;

    if (!s.swiping) {
      if (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        s.swiping = true;
      } else {
        return;
      }
    }

    let offset = s.currentOffset + dx;
    // Hard clamp — don't overshoot the zone
    if (offset > SWIPE_ZONE) offset = SWIPE_ZONE;
    if (offset < -SWIPE_ZONE) offset = -SWIPE_ZONE;

    this.setData({ [`items[${s.index}].swipeX`]: offset });
  },

  onItemTouchEnd(event) {
    if (!this._swipeState) return;
    const s = this._swipeState;
    const offset = this.data.items[s.index].swipeX || 0;

    if (!s.swiping) {
      this._springTo(s.index, 0);
      this._swipeState = null;
      return;
    }

    if (offset > SWIPE_THRESHOLD) {
      // Right swipe → toggle pin
      this._springTo(s.index, 0);
      this._swipeState = null;
      const item = this.data.items[s.index];
      this._doPin(item.id, item.pinned);
    } else if (offset < -SWIPE_THRESHOLD) {
      // Left swipe → delete confirm (wait for spring to finish)
      var self = this;
      var targetIndex = s.index;
      var item = this.data.items[s.index];
      this._swipeState = null;
      this._springTo(targetIndex, 0, function() {
        self._confirmSwipeDelete(item.id, targetIndex);
      });
    } else {
      this._springTo(s.index, 0);
      this._swipeState = null;
    }
  },

  _springTo(index, target, onComplete) {
    if (this._swipeSpring) this._swipeSpring.stop();
    var self = this;
    this._swipeSpring = spring(target, {
      damping: 0.75,
      response: 0.28,
      onUpdate: function(value) {
        self.setData({ [`items[${index}].swipeX`]: value });
      },
      onComplete: onComplete || null,
    });
  },

  _closeOtherSwipes(exceptIndex) {
    var items = this.data.items;
    var changed = false;
    var next = items.map(function(item, i) {
      if (i !== exceptIndex && item.swipeX !== 0) {
        changed = true;
        return { ...item, swipeX: 0 };
      }
      return item;
    });
    if (changed) this.setData({ items: next });
  },

  _closeAllSwipes() {
    var items = this.data.items;
    var changed = false;
    var next = items.map(function(item) {
      if (item.swipeX !== 0) {
        changed = true;
        return { ...item, swipeX: 0 };
      }
      return item;
    });
    if (changed) this.setData({ items: next });
    if (this._swipeSpring) {
      this._swipeSpring.stop();
      this._swipeSpring = null;
    }
    this._swipeState = null;
  },

  _doPin(id, currentPinned) {
    var newPinned = !currentPinned;

    if (this.data.organizeMode) {
      // AI 分组视图：组内按 _todoSort 重排（组标题行保持位置）
      this.patchGroupItem(id, { pinned: newPinned });
      this._renderOrganizeItems();
    } else {
      // Optimistic update + local sort (find by id, not index — sort-safe)
      var items = this.data.items.map(function(item) {
        return item.id === id ? { ...item, pinned: newPinned } : item;
      });
      this.setData({ items: items.sort(_todoSort) });
      this.patchGroupItem(id, { pinned: newPinned });
    }

    wx.vibrateShort({ type: 'light' });

    var self = this;
    api.updateTodo(id, { pinned: newPinned }).catch(function(err) {
      // Revert on failure — find by id
      self.patchGroupItem(id, { pinned: currentPinned });
      if (self.data.organizeMode) {
        self._renderOrganizeItems();
      } else {
        var reverted = self.data.items.map(function(item) {
          return item.id === id ? { ...item, pinned: currentPinned } : item;
        });
        self.setData({ items: reverted.sort(_todoSort) });
      }
      console.error('置顶操作失败:', err);
    });
  },

  _confirmSwipeDelete(id, index) {
    var self = this;
    wx.showModal({
      title: '删除待办',
      content: '确定删除这条待办？',
      success: function(res) {
        if (!res.confirm) return;
        self._doDelete(id, index);
      },
    });
  },

  _doDelete(id, index) {
    var self = this;
    this.setData({ [`items[${index}].deleting`]: true });
    setTimeout(function() {
      var prevItems = self.data.items;
      var prevTodos = self.data.todos;
      self.setData({
        items: prevItems.filter(function(item) { return item.id !== id; }),
        todos: self.removeFromGroups(prevTodos, id),
      });
      self._buildCalendar(); // dot marks refresh after removal
      self._syncTodayState(); // entry visibility + auto-leave organize when empty
      // 组织视图：重建 AI 分组，空组标题自动消失
      if (self.data.organizeMode) self._renderOrganizeItems();
      wx.vibrateShort({ type: 'medium' });
      api.deleteTodo(id).catch(function() {
        // Already removed from UI
      });
    }, 220);
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
      sheetMode: "edit",
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

  onMaskTap(event) {
    // Only close when tapping the mask background, not a child element
    if (event.target !== event.currentTarget) return;
    this.cancelEdit();
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

      this.setData({ editSubmitting: false });
      wx.vibrateShort({ type: "light" });
      this._animateSheetOut(0);
      await this.loadTodos();
    } catch (error) {
      wx.showToast({ title: error.message || "保存失败", icon: "none" });
      this.setData({ editSubmitting: false });
    }
  },

  // ========== Reminder (微信订阅消息提醒) ==========

  openReminderPanel(event) {
    const id = Number(event.currentTarget.dataset.id);
    const todo = this.findTodo(id);
    if (!todo) {
      wx.showToast({ title: "待办不存在", icon: "none" });
      return;
    }
    if (!todo.due_time) {
      // 缺少具体时间：提示并打开编辑面板引导补充
      wx.showToast({ title: "请先设置明确时间", icon: "none" });
      this.editTodo(event);
      return;
    }
    if (this._editCloseTimer) {
      clearTimeout(this._editCloseTimer);
      this._editCloseTimer = null;
    }
    const now = new Date();
    const base = dateTimeToDate(todo.due_date, todo.due_time);
    const options = REMIND_PRESETS.map((opt) => {
      const t = new Date(base.getTime() - opt.minutesBefore * 60000);
      const invalid = t <= now;
      return {
        label: opt.label,
        invalid,
        timeText: invalid ? "已过去" : toTimeStr(t),
        value: toIsoLocal(t),
      };
    });
    // 默认准时；准时已过（=待办时间已过，剩余时间不足任何档位）→ 不允许创建
    if (options[0].invalid) {
      wx.showToast({ title: "剩余时间不足，无法设置提醒", icon: "none" });
      return;
    }
    const customDefault = new Date(now.getTime() + 3600000);
    options.push({ label: "自定义日期和时间", invalid: false, timeText: "", value: "" });
    this.setData({
      sheetMode: "reminder",
      editVisible: true,
      remindTodoId: todo.id,
      remindTodoContent: todo.content,
      remindTodoDue: `${todo.due_date}${todo.due_time ? " " + todo.due_time : ""}`,
      remindOptions: options,
      remindSelected: 0,
      remindCustomDate: toDateStr(customDefault),
      remindCustomTime: toTimeStr(customDefault),
      remindSubmitting: false,
      remindHasActive: Boolean(todo.reminder),
    });
    this._measureAndOpenSheet();
  },

  onRemindOptionTap(event) {
    const idx = Number(event.currentTarget.dataset.index);
    const opt = this.data.remindOptions[idx];
    if (!opt) return;
    if (opt.invalid) {
      // 剩余时间不足以提前到该档位：提示并不允许选择
      wx.showToast({ title: "剩余时间不足，无法" + opt.label, icon: "none" });
      return;
    }
    this.setData({ remindSelected: idx });
  },

  onRemindCustomDateChange(event) {
    this.setData({ remindCustomDate: event.detail.value });
  },

  onRemindCustomTimeChange(event) {
    this.setData({ remindCustomTime: event.detail.value });
  },

  submitReminder() {
    if (this.data.remindSubmitting) return;
    const todoId = this.data.remindTodoId;
    const options = this.data.remindOptions;
    const selected = this.data.remindSelected;

    let remindAt;
    if (selected === REMIND_CUSTOM_INDEX) {
      remindAt =
        this.data.remindCustomDate + "T" + this.data.remindCustomTime + ":00+08:00";
      const t = parseIso(remindAt);
      if (!t || t <= new Date()) {
        wx.showToast({ title: "提醒时间必须晚于当前时间", icon: "none" });
        return;
      }
    } else {
      const opt = options[selected];
      if (!opt || opt.invalid) {
        wx.showToast({ title: "剩余时间不足，无法设置提醒", icon: "none" });
        return;
      }
      remindAt = opt.value;
    }

    const self = this;
    this.setData({ remindSubmitting: true });
    const templateId = config.SUBSCRIBE_TEMPLATE_ID;
    wx.requestSubscribeMessage({
      tmplIds: [templateId],
      success(res) {
        if (res[templateId] !== "accept") {
          self.setData({ remindSubmitting: false });
          wx.showToast({ title: "未授权订阅，无法设置提醒", icon: "none" });
          return;
        }
        api
          .setReminder(todoId, remindAt)
          .then((data) => {
            const reminder =
              data && data.reminder
                ? data.reminder
                : { remind_at: remindAt, status: "pending" };
            self.patchGroupItem(todoId, { reminder });
            self.setData({
              items: self.data.items.map((item) =>
                item.id === todoId ? { ...item, reminder } : item
              ),
              remindSubmitting: false,
              remindHasActive: true,
            });
            wx.vibrateShort({ type: "light" });
            self._animateSheetOut(0);
            wx.showToast({ title: "已设置提醒", icon: "none" });
          })
          .catch((err) => {
            self.setData({ remindSubmitting: false });
            wx.showToast({ title: err.message || "设置失败", icon: "none" });
          });
      },
      fail() {
        self.setData({ remindSubmitting: false });
        wx.showToast({ title: "订阅授权失败，请重试", icon: "none" });
      },
    });
  },

  cancelReminderFlow() {
    const todoId = this.data.remindTodoId;
    const self = this;
    wx.showModal({
      title: "取消提醒",
      content: "确定取消这条待办的提醒？",
      success(res) {
        if (!res.confirm) return;
        api
          .deleteReminder(todoId)
          .then(() => {
            self.patchGroupItem(todoId, { reminder: null });
            self.setData({
              items: self.data.items.map((item) =>
                item.id === todoId ? { ...item, reminder: null } : item
              ),
              remindHasActive: false,
            });
            wx.showToast({ title: "已取消提醒", icon: "none" });
            self._animateSheetOut(0);
          })
          .catch((err) => {
            wx.showToast({ title: err.message || "取消失败", icon: "none" });
          });
      },
    });
  },

  // ========== Composer bar (keyboard ⇄ voice) ==========

  onComposerToggle() {
    if (this.data.recording || this.data.panelActive) return;
    if (this.data.composerSubmitting) return;
    const next = this.data.composerMode === "keyboard" ? "voice" : "keyboard";
    if (next === "voice") {
      wx.hideKeyboard();
      this.setData({
        composerMode: "voice",
        composerFocus: false,
        expanded: false,
      });
    } else {
      // Switch to text input and focus immediately — keyboard pops up
      this.setData({ composerMode: "keyboard", composerFocus: true });
    }
  },

  onComposerTouchStart(event) {
    // Fallback stop: a recording may have started while the permission
    // dialog stole touchend — the next touch on the bar stops it.
    if (this.data.recording) {
      this.stopVoice();
      return;
    }
    if (this.data.panelActive) return;

    const touch = event.touches && event.touches[0];
    if (touch) this._voiceTouchStartY = touch.clientY;

    // Voice mode: press-to-talk immediately (keyboard mode has no gestures)
    if (this.data.composerMode === "voice") {
      this.startVoice();
    }
  },

  onComposerTouchMove(event) {
    if (this.data.recording) {
      this.onVoiceButtonMove(event);
    }
  },

  onComposerTouchEnd() {
    if (this.data.recording) {
      this.stopVoice();
    }
  },

  onComposerTouchCancel() {
    this.onComposerTouchEnd();
  },

  onComposerInput(event) {
    const value = event.detail.value;
    const cursor = Number(event.detail.cursor);
    const patch = {
      composerText: value,
      composerCursor: Number.isFinite(cursor) ? cursor : value.length,
    };
    if (!value) {
      patch.expandVisible = false;
      patch.composerOverflow = false;
      patch.composerTall = false;
    }
    this.setData(patch);
  },

  // The compact textarea grows naturally until its fifth visual line. At that
  // point auto-height is disabled and the fixed-height textarea scrolls.
  onComposerLineChange(event) {
    const detail = event.detail || {};
    const lineCount = Math.max(1, Number(detail.lineCount) || 1);
    const overflow = lineCount >= 5;
    this.setData({
      expandVisible: overflow,
      composerOverflow: overflow,
      composerTall: lineCount >= 3,
    });
  },

  onComposerConfirm() {
    // Android uses the return key for newlines and the in-bar arrow to submit.
    if (this.data.isIOS) this.submitComposerText();
  },

  // ---- Expanded composer ----

  openExpand() {
    if (this.data.expanded || this.data.composerMode !== "keyboard") return;
    this._switchComposerLayout(true);
  },

  closeExpand() {
    if (!this.data.expanded) return;
    this._switchComposerLayout(false);
  },

  _switchComposerLayout(expanded) {
    // The native textarea is intentionally remounted to reset its private
    // scrollTop. Ignore the outgoing node's blur while the new one focuses.
    this._composerSwitching = true;
    if (this._composerSwitchTimer) clearTimeout(this._composerSwitchTimer);
    this.setData({ expanded, composerFocus: true }, () => {
      this._composerSwitchTimer = setTimeout(() => {
        this._composerSwitching = false;
        this._composerSwitchTimer = null;
        if (
          this.data.composerMode === "keyboard"
          && !this.data.composerSubmitting
          && !this.data.panelActive
        ) {
          this.setData({ composerFocus: true });
        }
      }, 80);
    });
  },

  onComposerBlur(event) {
    const cursor = Number(event && event.detail && event.detail.cursor);
    const patch = {};
    if (Number.isFinite(cursor)) patch.composerCursor = cursor;
    if (!this._composerSwitching) patch.composerFocus = false;
    this.setData(patch);
  },

  async submitComposerText() {
    if (this.data.composerSubmitting) return;
    const content = this.data.composerText.trim();
    if (!content) {
      wx.showToast({ title: "内容不能为空", icon: "none" });
      return;
    }
    wx.hideKeyboard();

    // Clear the bar — the unified processing panel takes over.
    this.setData({
      composerSubmitting: true,
      composerText: "",
      composerCursor: -1,
      composerFocus: false,
      expanded: false,
      expandVisible: false,
      composerOverflow: false,
      composerTall: false,
    });

    const panel = this.selectComponent("#processingPanel");
    if (!panel || !panel.startText(content)) {
      this.setData({ composerSubmitting: false });
      wx.showToast({ title: "当前任务处理中", icon: "none" });
    }
  },

  // ========== Voice input ==========

  setupRecorder() {
    if (this.recorder) return;
    this.recorder = wx.getRecorderManager();

    this.recorder.onStart(() => {
      this.recorderStarted = true;
    });

    this.recorder.onStop((res) => {
      this.recorderStarted = false;

      // A max-duration auto-stop arrives while `recording` is still true.
      // Cancelled recordings clear both flags before onStop arrives.
      const shouldProcess = this._voiceShouldProcess || this.data.recording;
      this.setData({ recording: false, voiceCancelHover: false });
      if (!shouldProcess) return;
      this._voiceShouldProcess = false;

      const tempFilePath = res.tempFilePath;
      if (!tempFilePath) {
        this.setData({ panelActive: false });
        wx.showToast({ title: "录音文件获取失败", icon: "none" });
        return;
      }
      const panel = this.selectComponent("#processingPanel");
      if (!panel || !panel.startVoice(tempFilePath)) {
        this.setData({ panelActive: false });
        wx.showToast({ title: "当前任务处理中", icon: "none" });
      }
    });

    this.recorder.onError((error) => {
      this.recorderStarted = false;
      this._voiceShouldProcess = false;
      this.setData({ recording: false, panelActive: false });
      wx.showToast({ title: error.errMsg || "录音失败", icon: "none" });
    });
  },

  async startVoice() {
    // 防止：(a) 已在录音 (b) 权限 await 未完成时重入 (c) 原生 recorder 仍在停止中
    if (this.data.recording || this.data.panelActive || this.recorderStarted) return;
    if (this._voicePermissionPending) return;
    if (!api.getToken()) {
      wx.redirectTo({ url: "/pages/auth/auth" });
      return;
    }

    // ── Permission first (system dialog would steal touchend) ──
    this._voicePermissionPending = true;
    try {
      await this.ensureRecordPermission();
    } catch (_error) {
      this._voicePermissionPending = false;
      wx.showToast({ title: "请先授权麦克风", icon: "none" });
      return;
    }
    // stopVoice may have fired during await — abort if cancelled
    if (!this._voicePermissionPending) return;
    this._voicePermissionPending = false;

    // ── Visual feedback ──
    this.setData({
      recording: true,
      voiceCancelHover: false,
    });
    wx.vibrateShort({ type: "heavy" });

    // ── Start local recording ──
    try {
      this.recorder.start({
        duration: config.RECORD_MAX_DURATION,
        sampleRate: 16000,
        numberOfChannels: 1,
        format: "pcm",
        frameSize: 4,
      });
      // start() 后立即标记原生忙碌，防止 onStop 前快速重按再次 start()
      this.recorderStarted = true;
    } catch (error) {
      this.recorderStarted = false;
      this.setData({ recording: false });
      wx.showToast({ title: error.errMsg || error.message || "录音启动失败", icon: "none" });
    }
  },

  onVoiceButtonMove(event) {
    if (!this.data.recording) return;
    const touch = event.touches[0];
    if (!touch) return;
    const dy = this._voiceTouchStartY - touch.clientY;
    const threshold = 40; // px — swipe up threshold
    const over = dy > threshold;
    if (over !== this.data.voiceCancelHover) {
      this.setData({ voiceCancelHover: over });
      if (over) wx.vibrateShort({ type: "warning" });
    }
  },

  stopVoice() {
    // Permission check still pending — cancel it, startVoice will abort
    if (this._voicePermissionPending) {
      this._voicePermissionPending = false;
      this.setData({ recording: false, voiceCancelHover: false });
      return;
    }

    if (!this.data.recording) return;

    const cancelled = this.data.voiceCancelHover;

    // Set the hand-off flag before stop(): onStop timing differs by platform.
    this._voiceShouldProcess = !cancelled;
    this.stopRecorder();

    if (cancelled) {
      // Cancel — discard everything
      this.setData({ recording: false, voiceCancelHover: false });
      return;
    }

    // Normal release — onStop hands the temp file to the processing panel.
    this.setData({
      recording: false,
      panelActive: true,
      voiceCancelHover: false,
    });
  },

  ensureRecordPermission() {
    return new Promise((resolve, reject) => {
      wx.getSetting({
        success: (settings) => {
          if (settings.authSetting["scope.record"]) {
            resolve();
            return;
          }
          wx.authorize({ scope: "scope.record", success: resolve, fail: reject });
        },
        fail: reject,
      });
    });
  },

  stopRecorder() {
    try {
      this.recorder.stop();
    } catch (error) {
      this.recorderStarted = false;
    }
  },

  onPanelStateChange(event) {
    const active = !!event.detail.active;
    const patch = { panelActive: active };
    if (!active) patch.composerSubmitting = false;
    this.setData(patch);
  },

  async onPanelSaved() {
    await this.loadTodos();
    setTimeout(() => this._measureTabs(), 200);
  },

  onPanelRerecord() {
    this.setData({ composerMode: "voice", panelActive: false });
    wx.showToast({ title: "请按住说话", icon: "none" });
  },

  // ========== Cleanup ==========

  _stopAllSprings() {
    const springs = [
      this._pillSpring, this._sheetSpring, this._voiceSpring, this._maskSpring,
      this._swipeSpring, this._calSpring,
    ];
    springs.forEach((s) => { if (s) s.stop(); });
    Object.values(this._checkSprings).forEach((s) => { if (s) s.stop(); });
  },
});
