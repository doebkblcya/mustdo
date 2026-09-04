const api = require("../../utils/api");
const preferences = require("../../utils/preferences");

const IN_FLIGHT = ["uploading", "transcribing", "parsing", "saving"];

function initialPanel() {
  return {
    phase: "idle",
    mode: "auto",
    source: "text",
    transcript: "",
    items: [],
    created: [],
    message: "",
    errorStep: "",
    tempFilePath: "",
  };
}

function errorCode(error) {
  return error && error.payload && error.payload.code ? error.payload.code : "";
}

Component({
  properties: {
    todayDate: {
      type: String,
      value: "",
    },
  },

  data: {
    panel: initialPanel(),
    visible: false,
    steps: [],
    rerecordOnly: false,
    canClose: false,
  },

  lifetimes: {
    detached() {
      this._clearDoneTimer();
    },
  },

  methods: {
    isBusy() {
      return this.data.visible;
    },

    startText(transcript) {
      if (this.data.visible || !transcript) return false;
      this._replacePanel({
        ...initialPanel(),
        phase: "parsing",
        mode: preferences.getAddMode(),
        source: "text",
        transcript,
      });
      this._parse();
      return true;
    },

    startVoice(tempFilePath) {
      if (this.data.visible || !tempFilePath) return false;
      this._replacePanel({
        ...initialPanel(),
        phase: "uploading",
        mode: preferences.getAddMode(),
        source: "voice",
        tempFilePath,
      });
      this._uploadAndTranscribe();
      return true;
    },

    _replacePanel(panel) {
      const visible = panel.phase !== "idle";
      this.setData({
        panel,
        visible,
        steps: this._buildSteps(panel),
        rerecordOnly: false,
        // 关闭入口只在「确认待办」和错误态出现；其余阶段（含全绿收尾停留）自动走
        canClose: visible && (panel.phase === "reviewing" || panel.phase === "error"),
      });
      this.triggerEvent("statechange", { active: visible, phase: panel.phase });
    },

    _patchPanel(patch) {
      const panel = { ...this.data.panel, ...patch };
      this._replacePanel(panel);
    },

    _buildSteps(panel) {
      const defs = [
        { key: "source", label: panel.source === "voice" ? "语音识别" : "文字输入" },
        { key: "parsing", label: "AI 解析" },
        { key: "saving", label: "保存待办" },
      ];
      // saved：保存成功收尾（三步全绿停留后自动关）；no_result：解析出 0 条（提示后停留自动关）
      const allComplete = panel.phase === "saved";
      const zeroResult = panel.phase === "no_result";
      let currentKey = panel.phase;
      if (panel.phase === "uploading" || panel.phase === "transcribing") currentKey = "source";
      if (panel.phase === "reviewing") currentKey = "saving";
      if (panel.phase === "error") {
        currentKey = panel.errorStep === "uploading" || panel.errorStep === "transcribing"
          ? "source"
          : panel.errorStep;
      }
      const current = defs.findIndex((item) => item.key === currentKey);
      return defs.map((item, index) => {
        let state = "pending";
        if (allComplete) state = "complete";
        else if (zeroResult) state = index <= 1 ? "complete" : "pending";
        else if (index < current) state = "complete";
        else if (index === current) state = panel.phase === "error" ? "error" : "active";
        if (panel.source === "text" && item.key === "source") state = "complete";
        if (panel.phase === "reviewing" && item.key === "saving") state = "pending";
        let summary = "";
        // 语音识别 / 文字输入：步骤下展示转写或输入内容
        if (item.key === "source" && panel.transcript) summary = panel.transcript;
        // AI 解析：解析出 0 条时在步骤下提示（有条目时仅展开条目列表，不再显示 N 项计数）
        if (item.key === "parsing" && panel.phase === "no_result") {
          summary = panel.message || "没有识别到需要新增的待办";
        }
        // 保存待办：步骤下不展示内容
        return { ...item, state, summary };
      });
    },

    async _uploadAndTranscribe() {
      const path = this.data.panel.tempFilePath;
      this._patchPanel({ phase: "uploading", errorStep: "", message: "" });
      try {
        const result = await api.uploadVoice(path, () => {
          if (this.data.panel.phase === "uploading") {
            this._patchPanel({ phase: "transcribing" });
          }
        });
        const transcript = (result && result.transcript || "").trim();
        if (!transcript) {
          this._setError("transcribing", "没有识别到声音，请重新录音", true);
          return;
        }
        this._patchPanel({ phase: "parsing", transcript });
        await this._parse();
      } catch (error) {
        const code = errorCode(error);
        const audioCodes = [
          "recording_too_short",
          "recording_too_long",
          "unsupported_audio",
          "audio_transcode_failed",
        ];
        const rerecord = audioCodes.includes(code);
        const step = audioCodes.includes(code)
          ? "uploading"
          : (this.data.panel.phase === "transcribing" ? "transcribing" : "uploading");
        this._setError(step, error.message || "语音识别失败", rerecord);
      }
    },

    async _parse() {
      const panel = this.data.panel;
      if (!panel.transcript.trim()) return;
      this._patchPanel({ phase: "parsing", errorStep: "", message: "", created: [] });
      try {
        const result = await api.parseTodos(panel.transcript.trim(), panel.source);
        const items = (result.items || []).map((item, index) => ({
          ...item,
          _key: Date.now() + "-" + index,
        }));
        const message = result.message || "";
        if (this.data.panel.mode === "confirm") {
          this._patchPanel({ phase: "reviewing", transcript: result.transcript, items, message });
          return;
        }
        if (!items.length) {
          // 自动模式解析出 0 条：AI 解析步骤下提示，停留后自动关闭（无成功卡）
          this._settleNoResult(message || "没有识别到需要新增的待办");
          return;
        }
        this._patchPanel({ phase: "saving", transcript: result.transcript, items, message: "" });
        await this._save();
      } catch (error) {
        this._setError("parsing", error.message || "解析失败");
      }
    },

    async _save() {
      const items = this.data.panel.items.map((item) => ({
        content: item.content.trim(),
        due_date: item.due_date,
        due_time: item.due_time || null,
      }));
      if (!items.length) return;
      this._patchPanel({ phase: "saving", errorStep: "", message: "" });
      try {
        const result = await api.batchCreateTodos(items);
        this._settleSaved(result.items || []);
      } catch (error) {
        this._setError("saving", error.message || "保存失败");
      }
    },

    // 保存成功：步骤条三步全绿停留（1.3s）让用户看清后自动关闭，无 done 成功卡
    _settleSaved(created) {
      this._patchPanel({ phase: "saved", created, message: "" });
      if (created.length) {
        wx.vibrateShort({ type: "light" });
        this.triggerEvent("saved", { items: created });
      }
      this._doneTimer = setTimeout(() => this._closeNow(), 1300);
    },

    // 自动模式解析 0 条：AI 解析步骤下提示文案，短暂停留后自动关闭
    _settleNoResult(message) {
      this._patchPanel({
        phase: "no_result",
        created: [],
        message: message || "没有识别到需要新增的待办",
      });
      this._doneTimer = setTimeout(() => this._closeNow(), 1300);
    },

    _setError(step, message, rerecordOnly) {
      this._patchPanel({ phase: "error", errorStep: step, message });
      this.setData({ rerecordOnly: !!rerecordOnly });
    },

    retry() {
      const step = this.data.panel.errorStep;
      if (this.data.rerecordOnly) {
        this.rerecord();
      } else if (step === "uploading" || step === "transcribing") {
        this._uploadAndTranscribe();
      } else if (step === "parsing") {
        this._parse();
      } else if (step === "saving") {
        this._save();
      }
    },

    rerecord() {
      this._closeNow();
      this.triggerEvent("rerecord");
    },

    onTranscriptInput(event) {
      this._clearDoneTimer();
      this._patchPanel({ transcript: event.detail.value });
    },

    reparse() {
      if (!this.data.panel.transcript.trim()) {
        wx.showToast({ title: "内容不能为空", icon: "none" });
        return;
      }
      this._parse();
    },

    onItemContentInput(event) {
      this._updateItem(Number(event.currentTarget.dataset.index), "content", event.detail.value);
    },

    onItemDateChange(event) {
      this._updateItem(Number(event.currentTarget.dataset.index), "due_date", event.detail.value);
    },

    onItemTimeChange(event) {
      this._updateItem(Number(event.currentTarget.dataset.index), "due_time", event.detail.value);
    },

    clearItemTime(event) {
      this._updateItem(Number(event.currentTarget.dataset.index), "due_time", null);
    },

    _updateItem(index, field, value) {
      const items = this.data.panel.items.slice();
      if (!items[index]) return;
      items[index] = { ...items[index], [field]: value };
      this._patchPanel({ items });
    },

    deleteItem(event) {
      const index = Number(event.currentTarget.dataset.index);
      const items = this.data.panel.items.filter((_item, itemIndex) => itemIndex !== index);
      this._patchPanel({ items });
    },

    confirmSave() {
      const invalid = this.data.panel.items.some((item) => !item.content.trim());
      if (invalid) {
        wx.showToast({ title: "待办内容不能为空", icon: "none" });
        return;
      }
      if (this.data.panel.items.length) this._save();
    },

    requestClose() {
      this._clearDoneTimer();
      const panel = this.data.panel;
      if (IN_FLIGHT.includes(panel.phase)) return;
      if (panel.phase === "reviewing" && panel.items.length) {
        wx.showModal({
          title: "放弃这次添加？",
          content: "转写和待审核的待办将被丢弃。",
          confirmText: "放弃",
          confirmColor: "#d14343",
          success: (result) => {
            if (result.confirm) this._closeNow();
          },
        });
        return;
      }
      this._closeNow();
    },

    _closeNow() {
      this._clearDoneTimer();
      this._replacePanel(initialPanel());
    },

    _clearDoneTimer() {
      if (this._doneTimer) {
        clearTimeout(this._doneTimer);
        this._doneTimer = null;
      }
    },

    noop() {},
  },
});
