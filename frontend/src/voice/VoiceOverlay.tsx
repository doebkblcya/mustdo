import type { VoiceOverlayState } from "./types";
import { CloseIcon } from "../components/Icons";
import { formatDate } from "../utils/date";

interface VoiceOverlayProps {
  overlay: VoiceOverlayState | null;
  onClose: () => void;
}

const titleMap: Record<VoiceOverlayState["status"], string> = {
  preparing: "准备语音服务",
  recording: "正在录音",
  transcribing: "正在转文字",
  parsing: "正在解析待办",
  success: "已添加",
  empty: "未添加待办",
  error: "处理失败",
};

export function VoiceOverlay({ overlay, onClose }: VoiceOverlayProps) {
  if (!overlay) return null;
  const busy = ["preparing", "recording", "transcribing", "parsing"].includes(overlay.status);
  const closable = ["empty", "error"].includes(overlay.status);
  const title = overlay.status === "error" ? overlay.title || titleMap.error : titleMap[overlay.status];

  return (
    <div className="overlay-backdrop">
      <section className="parse-panel">
        <div className="parse-header">
          <h2 className="parse-title">{title}</h2>
          {closable ? (
            <button className="icon-button" type="button" title="关闭" aria-label="关闭" onClick={onClose}>
              <CloseIcon />
            </button>
          ) : null}
        </div>
        <div className="parse-status">
          {busy ? <span className="spinner" /> : <span className={`status-dot ${overlay.status === "error" ? "error" : ""}`} />}
          <span>{overlay.message || title}</span>
        </div>
        {overlay.transcript ? <div className="transcript-box">{overlay.transcript}</div> : null}
        {overlay.items?.length ? (
          <div className="result-list">
            {overlay.items.map((item) => (
              <div className="result-row" key={item.id}>
                <span>{item.content}</span>
                <span className="result-date">
                  {formatDate(item.due_date)}
                  {item.due_time ? ` ${item.due_time}` : ""}
                </span>
              </div>
            ))}
          </div>
        ) : null}
        {overlay.error ? <div className="error-text">{overlay.error}</div> : null}
      </section>
    </div>
  );
}
