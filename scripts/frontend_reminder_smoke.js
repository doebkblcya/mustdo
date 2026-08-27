// 前端提醒逻辑冒烟测试（Node 桩件，无微信 devtools）
// 运行：node scripts/frontend_reminder_smoke.js
// 覆盖：预设时间降级选择、ISO 时间换算、自定义时间提交、授权流提交、
//       完成/移到明天对本地提醒状态的联动清空。
"use strict";

const assert = require("assert");
const path = require("path");

const MP_DIR = path.resolve(__dirname, "../miniprogram");
const config = require(path.join(MP_DIR, "config.js"));

// ---------- wx 桩件 ----------
let subscribeOpts = null;
global.wx = {
  showToast: () => {},
  showModal: (opts) => {
    if (opts && opts.success) opts.success({ confirm: true });
  },
  vibrateShort: () => {},
  requestSubscribeMessage: (opts) => {
    subscribeOpts = opts;
    const res = {};
    res[config.SUBSCRIBE_TEMPLATE_ID] = "accept";
    opts.success(res);
  },
  createSelectorQuery: () => ({
    select: () => ({ boundingClientRect: () => ({ exec: (cb) => cb([null]) }) }),
    exec: (cb) => cb([]),
  }),
  getWindowInfo: () => ({ windowHeight: 800 }),
  getDeviceInfo: () => ({ platform: "ios" }),
  onKeyboardHeightChange: () => {},
  getStorageSync: () => null,
  setStorageSync: () => {},
  redirectTo: () => {},
  navigateTo: () => {},
  hideKeyboard: () => {},
};

// ---------- 捕获 Page 配置 ----------
let pageConfig = null;
global.Page = (cfg) => {
  pageConfig = cfg;
};
require(path.join(MP_DIR, "pages/todos/todos.js"));
assert.ok(pageConfig, "Page config captured");

// api 模块：后续可打桩（todos.js 持有同一 exports 对象）
const api = require(path.join(MP_DIR, "utils/api.js"));

// ---------- 实例化 ----------
function makeInstance() {
  const inst = Object.create(pageConfig);
  inst.data = JSON.parse(JSON.stringify(pageConfig.data));
  inst.setData = function (patch) {
    for (const key of Object.keys(patch)) {
      const segs = key.split(/[\[\].]/).filter(Boolean);
      let obj = this.data;
      for (let i = 0; i < segs.length - 1; i++) {
        const s = segs[i];
        obj = obj[s] === undefined ? (obj[s] = {}) : obj[s];
      }
      obj[segs[segs.length - 1]] = patch[key];
    }
  };
  return inst;
}

function seedTodo(id, dueDateTime) {
  // dueDateTime: Date 对象
  const pad = (n) => (n < 10 ? "0" + n : "" + n);
  return {
    id,
    content: "冒烟待办" + id,
    due_date: `${dueDateTime.getFullYear()}-${pad(dueDateTime.getMonth() + 1)}-${pad(dueDateTime.getDate())}`,
    due_time: `${pad(dueDateTime.getHours())}:${pad(dueDateTime.getMinutes())}`,
    status: "pending",
    pinned: false,
    reminder: null,
    key: id,
    meta: "",
    checkScale: 1,
    deleting: false,
    swipeX: 0,
  };
}

function seedInstance(todos) {
  const inst = makeInstance();
  const groups = { today: [], tomorrow: [], upcoming: [] };
  todos.forEach((t) => groups.today.push(t));
  inst.data.todos = {
    today_date: groups.today[0].due_date,
    tomorrow_date: "",
    groups,
  };
  inst.data.todayDate = groups.today[0].due_date;
  inst.data.items = groups.today.map((t) => ({ ...t }));
  return inst;
}

const tap = (id) => ({ currentTarget: { dataset: { id } } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- 用例 ----------

async function testPresetFallback() {
  const now = new Date();

  // A：全部有效（截止 3 小时后）→ 默认选中「提前 30 分钟」(index 2)
  const dueA = new Date(now.getTime() + 3 * 3600000);
  const instA = seedInstance([seedTodo(1, dueA)]);
  instA.openReminderPanel(tap(1));
  assert.strictEqual(instA.data.remindSelected, 2, "A: 默认提前30分钟");
  assert.strictEqual(instA.data.remindOptions.length, 5, "A: 4预设+自定义");
  assert.ok(!instA.data.remindOptions[2].invalid, "A: 提前30有效");
  assert.strictEqual(instA.data.sheetMode, "reminder", "A: 弹层为提醒模式");

  // B：提前30 已过（截止 15 分钟后）→ 降级「提前 10 分钟」(index 1)
  const dueB = new Date(now.getTime() + 15 * 60000);
  const instB = seedInstance([seedTodo(2, dueB)]);
  instB.openReminderPanel(tap(2));
  assert.strictEqual(instB.data.remindOptions[2].invalid, true, "B: 提前30已过");
  assert.strictEqual(instB.data.remindSelected, 1, "B: 降级提前10分钟");

  // C：全部已过（截止 1 小时前）→ 引导自定义 (index 4)
  const dueC = new Date(now.getTime() - 3600000);
  const instC = seedInstance([seedTodo(3, dueC)]);
  instC.openReminderPanel(tap(3));
  assert.ok(
    instC.data.remindOptions.slice(0, 4).every((o) => o.invalid),
    "C: 全部预设已过"
  );
  assert.strictEqual(instC.data.remindSelected, 4, "C: 自动选中自定义");

  // 无 due_time → 引导编辑面板
  const todoNoTime = seedTodo(4, new Date());
  todoNoTime.due_time = null;
  const instD = seedInstance([todoNoTime]);
  instD.openReminderPanel(tap(4));
  assert.strictEqual(instD.data.sheetMode, "edit", "D: 无时间→编辑面板");
  console.log("  ✓ 预设降级选择");
}

async function testIsoRoundTrip() {
  // 通过 openReminderPanel 产物验证 toIsoLocal 输出
  const now = new Date();
  const due = new Date(now.getTime() + 3 * 3600000);
  const inst = seedInstance([seedTodo(5, due)]);
  inst.openReminderPanel(tap(5));
  const v = inst.data.remindOptions[2].value;
  assert.match(v, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+08:00$/, "ISO 格式");
  // 与截止时间相差 30 分钟
  const pad = (n) => (n < 10 ? "0" + n : "" + n);
  const due30 = new Date(due.getTime() - 30 * 60000);
  const expect = `${due30.getFullYear()}-${pad(due30.getMonth() + 1)}-${pad(due30.getDate())}T${pad(due30.getHours())}:${pad(due30.getMinutes())}:00+08:00`;
  assert.strictEqual(v, expect, "提前30分钟换算");
  console.log("  ✓ ISO 时间换算");
}

async function testSubmitReminder() {
  const now = new Date();
  const due = new Date(now.getTime() + 3 * 3600000);
  const inst = seedInstance([seedTodo(6, due)]);
  inst.openReminderPanel(tap(6));

  // 预设路径：提前30分钟
  let sent = null;
  api.setReminder = async (todoId, remindAt) => {
    sent = { todoId, remindAt };
    return { reminder: { remind_at: remindAt, status: "pending" } };
  };
  inst.setData({ remindSelected: 2 });
  inst.submitReminder();
  await sleep(5);
  assert.strictEqual(sent.todoId, 6, "预设: todo id");
  assert.strictEqual(sent.remindAt, inst.data.remindOptions[2].value, "预设: remind_at");
  assert.ok(inst.data.remindHasActive, "预设: 卡片提醒态开启");
  assert.strictEqual(inst.data.todos.groups.today[0].reminder.status, "pending", "预设: 组数据更新");

  // 自定义路径：构造 +08:00 时间
  sent = null;
  inst.data.todos.groups.today[0].reminder = null;
  inst.openReminderPanel(tap(6));
  inst.setData({ remindSelected: 4, remindCustomDate: "2099-01-01", remindCustomTime: "10:00" });
  inst.submitReminder();
  await sleep(5);
  assert.strictEqual(sent.remindAt, "2099-01-01T10:00:00+08:00", "自定义: remind_at 拼接");

  // 自定义时间在过去 → 本地拦截不提交
  sent = null;
  inst.setData({ remindCustomDate: "2000-01-01", remindCustomTime: "00:00" });
  inst.submitReminder();
  await sleep(5);
  assert.strictEqual(sent, null, "自定义: 过去时间被拦截");
  console.log("  ✓ 授权流提交（accept 路径 + 自定义校验）");
}

async function testLinkageClearsReminder() {
  const now = new Date();
  const due = new Date(now.getTime() + 3 * 3600000);
  const todo = seedTodo(7, due);
  todo.reminder = { remind_at: "2099-01-01T10:00:00+08:00", status: "pending" };
  const inst = seedInstance([todo]);

  // 完成 → 本地清空提醒
  api.updateTodo = async () => ({});
  inst.toggleTodo({ currentTarget: { dataset: { id: 7, status: "pending", index: 0 } } });
  await sleep(5);
  assert.strictEqual(inst.data.todos.groups.today[0].reminder, null, "完成: 提醒清空");
  assert.strictEqual(inst.data.items[0].reminder, null, "完成: items 同步");

  // 移到明天 → 本地清空提醒（后端因改期联动取消）
  const todo8 = seedTodo(8, due);
  todo8.reminder = { remind_at: "2099-01-01T10:00:00+08:00", status: "pending" };
  const inst2 = seedInstance([todo8]);
  inst2.data.todos.tomorrow_date = "2099-12-31";
  inst2.moveToTomorrow(tap(8));
  await sleep(5);
  const moved = inst2.data.todos.groups.tomorrow.find((t) => t.id === 8);
  assert.ok(moved, "移到明天: 进入明天组");
  assert.strictEqual(moved.reminder, null, "移到明天: 提醒清空");
  console.log("  ✓ 完成/移到明天的提醒联动");
}

async function testFormatRemindAt() {
  const inst = makeInstance();
  inst.data.todayDate = "2026-08-25";
  assert.strictEqual(inst.formatRemindAt("2026-08-25T14:30:00+08:00"), "今天 14:30");
  assert.strictEqual(inst.formatRemindAt("2026-08-27T09:05:00+08:00"), "8月27日 09:05");
  assert.strictEqual(inst.formatRemindAt(null), "");
  console.log("  ✓ formatRemindAt 展示");
}

(async () => {
  console.log("frontend_reminder_smoke:");
  await testPresetFallback();
  await testIsoRoundTrip();
  await testSubmitReminder();
  await testLinkageClearsReminder();
  await testFormatRemindAt();
  console.log("ALL PASS");
  process.exit(0);
})().catch((err) => {
  console.error("FAIL:", err);
  process.exit(1);
});
