import type { TodoPublic } from "../api/types";

export type VoiceOverlayStatus =
  | "preparing"
  | "recording"
  | "transcribing"
  | "parsing"
  | "success"
  | "empty"
  | "error";

export interface VoiceOverlayState {
  status: VoiceOverlayStatus;
  title?: string;
  message?: string;
  transcript?: string;
  items?: TodoPublic[];
  error?: string;
}

export interface VoiceStreamMessage {
  type: "ready" | "partial" | "status" | "final" | "error";
  text?: string;
  transcript?: string;
  message?: string;
  error?: string;
}
