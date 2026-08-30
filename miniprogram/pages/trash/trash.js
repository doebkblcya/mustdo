var api = require("../../utils/api");

// "2026-08-20T14:30:00+08:00" → "8月20日 14:30"
function formatDateTime(iso) {
  if (!iso) return "";
  var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return "";
  return parseInt(m[2], 10) + "月" + parseInt(m[3], 10) + "日 " + m[4] + ":" + m[5];
}

function formatDateCN(dateStr) {
  if (!dateStr) return "";
  var parts = dateStr.split("-");
  if (parts.length !== 3) return dateStr;
  return parseInt(parts[1], 10) + "月" + parseInt(parts[2], 10) + "日";
}

function todayStr() {
  var d = new Date();
  var mm = d.getMonth() + 1 < 10 ? "0" + (d.getMonth() + 1) : "" + (d.getMonth() + 1);
  var dd = d.getDate() < 10 ? "0" + d.getDate() : "" + d.getDate();
  return d.getFullYear() + "-" + mm + "-" + dd;
}

function daysBetween(aStr, bStr) {
  var a = new Date(aStr + "T00:00:00");
  var b = new Date(bStr + "T00:00:00");
  return Math.round((a - b) / 86400000);
}

Page({
  // 请求序号：快速切换 tab 时丢弃过期响应，避免旧列表覆盖新 tab
  _reqSeq: 0,

  data: {
    statusBarHeight: 0,
    headerRightOffset: 12,
    navTop: 24,
    navHeight: 32,
    activeTab: "deleted",
    deletedCount: 0,
    overdueCount: 0,
    items: [],
    loading: false,
    error: "",
    todayDate: "",

    // 编辑 bottom sheet（简化版，无拖拽动画）
    editVisible: false,
    editTodoId: null,
    editContent: "",
    editDate: "",
    editTime: "",
    editUseTime: false,
    editSubmitting: false,
  },

  onLoad() {
    if (!api.getToken()) {
      wx.redirectTo({ url: "/pages/auth/auth" });
      return;
    }
    var windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    var menuButton = wx.getMenuButtonBoundingClientRect ? wx.getMenuButtonBoundingClientRect() : null;
    this.setData({
      statusBarHeight: windowInfo.statusBarHeight || 0,
      headerRightOffset: menuButton ? windowInfo.windowWidth - menuButton.left + 4 : 12,
      navTop: menuButton ? menuButton.top : (windowInfo.statusBarHeight || 0),
      navHeight: menuButton ? menuButton.height : 32,
      todayDate: todayStr(),
    });
    this.loadList();
  },

  onPullDownRefresh() {
    var self = this;
    this.loadList().finally(function() {
      wx.stopPullDownRefresh();
    });
  },

  async loadList(tab) {
    var target = tab || this.data.activeTab;
    var seq = ++this._reqSeq;
    this.setData({ loading: true, error: "" });
    try {
      var res = await api.listTrash(target);
      if (seq !== this._reqSeq) return; // 过期响应，丢弃
      this.setData({
        deletedCount: res.deleted_count || 0,
        overdueCount: res.overdue_count || 0,
      });
      this._applyItems(res.items || [], target);
      this.setData({ loading: false });
    } catch (error) {
      if (error.statusCode === 401) {
        api.clearSession();
        wx.redirectTo({ url: "/pages/auth/auth" });
        return;
      }
      if (seq !== this._reqSeq) return; // 过期失败态，丢弃
      this.setData({ loading: false, error: error.message || "加载失败" });
    }
  },

  switchTab(event) {
    var tab = event.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    this.setData({ activeTab: tab });
    this.loadList(tab);
  },

  // tab 参数来自发起请求时的值，不读当前 activeTab（防并发错乱）
  _applyItems(rows, tab) {
    var today = this.data.todayDate;
    var isDeleted = tab === "deleted";
    var items = rows.map(function(item) {
      var meta = "原定 " + formatDateCN(item.due_date);
      if (item.due_time) meta += " " + item.due_time;
      if (isDeleted) {
        meta += " · 删除于 " + formatDateTime(item.deleted_at);
      } else {
        meta += " · 逾期 " + daysBetween(today, item.due_date) + " 天";
      }
      return {
        id: item.id,
        content: item.content,
        status: item.status,
        due_date: item.due_date,
        due_time: item.due_time,
        meta: meta,
        key: item.id,
      };
    });
    this.setData({ items: items });
  },

  _removeItem(id) {
    this.setData({ items: this.data.items.filter(function(item) { return item.id !== id; }) });
  },

  _refreshCounts() {
    api.listTrash().then((res) => {
      this.setData({
        deletedCount: res.deleted_count || 0,
        overdueCount: res.overdue_count || 0,
      });
    }).catch(function() {});
  },

  _toast(msg) {
    wx.showToast({ title: msg, icon: "none" });
  },

  // ---- 已删除：恢复（原日期早于今天 → 归正为今天） ----
  onRestore(event) {
    var id = Number(event.currentTarget.dataset.id);
    var item = this.data.items.find(function(i) { return i.id === id; });
    if (!item) return;
    var dueDate = item.due_date >= this.data.todayDate ? item.due_date : this.data.todayDate;
    api.updateTodo(id, { deleted_at: null, due_date: dueDate })
      .then(() => {
        this._removeItem(id);
        this._toast("已恢复");
        this._refreshCounts();
      })
      .catch((err) => this._toast(err.message || "恢复失败"));
  },

  // ---- 已逾期：移到今天 ----
  onMoveToday(event) {
    var id = Number(event.currentTarget.dataset.id);
    api.updateTodo(id, { due_date: this.data.todayDate })
      .then(() => {
        this._removeItem(id);
        this._toast("已移到今天");
        this._refreshCounts();
      })
      .catch((err) => this._toast(err.message || "操作失败"));
  },

  // ---- 已逾期：完成 ----
  onToggleDone(event) {
    var id = Number(event.currentTarget.dataset.id);
    api.updateTodo(id, { status: "done" })
      .then(() => {
        this._removeItem(id);
        this._toast("已完成");
        this._refreshCounts();
      })
      .catch((err) => this._toast(err.message || "操作失败"));
  },

  // ---- 已逾期：删除（软删除 → 进入已删除视图，开始 7 天窗口） ----
  onDelete(event) {
    var id = Number(event.currentTarget.dataset.id);
    var self = this;
    wx.showModal({
      title: "删除待办",
      content: "确定删除这条待办？7 天内可在已删除中恢复。",
      success: function(res) {
        if (!res.confirm) return;
        api.deleteTodo(id)
          .then(function() {
            self._removeItem(id);
            self._refreshCounts();
          })
          .catch(function(err) { self._toast(err.message || "删除失败"); });
      },
    });
  },

  // ---- 编辑（逾期项可改内容/日期/时间） ----
  onEdit(event) {
    var id = Number(event.currentTarget.dataset.id);
    var item = this.data.items.find(function(i) { return i.id === id; });
    if (!item) return;
    this.setData({
      editVisible: true,
      editTodoId: id,
      editContent: item.content,
      editDate: item.due_date,
      editTime: item.due_time || "09:00",
      editUseTime: Boolean(item.due_time),
      editSubmitting: false,
    });
  },

  onMaskTap(event) {
    if (event.target !== event.currentTarget) return;
    this.cancelEdit();
  },

  noop() {},

  cancelEdit() {
    if (this.data.editSubmitting) return;
    this.setData({ editVisible: false, editTodoId: null });
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

  async submitEdit() {
    if (this.data.editSubmitting) return;
    var content = this.data.editContent.trim();
    if (!content) {
      this._toast("内容不能为空");
      return;
    }
    this.setData({ editSubmitting: true });
    try {
      await api.updateTodo(this.data.editTodoId, {
        content: content,
        due_date: this.data.editDate,
        due_time: this.data.editUseTime ? this.data.editTime : null,
      });
      this.setData({ editSubmitting: false, editVisible: false, editTodoId: null });
      this._toast("已保存");
      this.loadList();
    } catch (error) {
      this.setData({ editSubmitting: false });
      this._toast(error.message || "保存失败");
    }
  },
});
