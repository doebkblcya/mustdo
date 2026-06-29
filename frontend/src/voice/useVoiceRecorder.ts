import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";

import { createTodosFromTranscript, voiceStreamUrl } from "../api/client";
import { downsampleBuffer, floatTo16BitPcm, TARGET_SAMPLE_RATE } from "./audio";
import type { VoiceOverlayState, VoiceStreamMessage } from "./types";

const SUCCESS_CLOSE_MS = 1800;
const MAX_RECORDING_MS = 30_000;
const MIN_RECORDING_SECONDS = 0.5;
const STREAM_READY_TIMEOUT_MS = 5000;
const STREAM_RESULT_TIMEOUT_MS = 90_000;

type AudioContextConstructor = typeof AudioContext;

interface RecordingSession {
  stream: MediaStream;
  context: AudioContext;
  source: MediaStreamAudioSourceNode;
  processor: ScriptProcessorNode;
  zeroGain: GainNode;
  socket: WebSocket;
  socketReady: boolean;
  socketClosedByClient: boolean;
  pendingBytes: Uint8Array;
  audioBytes: number;
  transcript: string;
  finalTranscript: string;
  streamError: Error | null;
  sampleRate: number;
  timeoutId: number;
  captureStopped?: boolean;
  readyPromise: Promise<void>;
  finalPromise: Promise<string>;
  resolveReady?: () => void;
  rejectReady?: (error: Error) => void;
  resolveFinal?: (value: string) => void;
  rejectFinal?: (error: Error) => void;
}

export function useVoiceRecorder(onTodosCreated: () => Promise<void>) {
  const [recording, setRecording] = useState(false);
  const [overlay, setOverlay] = useState<VoiceOverlayState | null>(null);
  const recordingRef = useRef<RecordingSession | null>(null);
  const stopRequestedRef = useRef(false);
  const successTimerRef = useRef<number | null>(null);

  const clearSuccessTimer = useCallback(() => {
    if (successTimerRef.current !== null) {
      window.clearTimeout(successTimerRef.current);
      successTimerRef.current = null;
    }
  }, []);

  const showOverlay = useCallback(
    (next: VoiceOverlayState | null) => {
      clearSuccessTimer();
      setOverlay(next);
    },
    [clearSuccessTimer],
  );

  const closeOverlay = useCallback(() => setOverlay(null), []);

  const stopRecording = useCallback(async () => {
    const session = recordingRef.current;
    if (!session) {
      stopRequestedRef.current = true;
      return;
    }
    recordingRef.current = null;
    stopRequestedRef.current = false;
    setRecording(false);
    stopRecordingCapture(session);

    try {
      const duration = session.audioBytes / (TARGET_SAMPLE_RATE * 2);
      if (duration < MIN_RECORDING_SECONDS) {
        closeRecordingSocket(session);
        showOverlay({ status: "error", title: "语音失败", error: "录音太短" });
        return;
      }
      const transcript = await finishVoiceStream(session, showOverlay);
      await createTodosFromTranscriptAndRefresh(transcript, showOverlay, onTodosCreated);
      successTimerRef.current = window.setTimeout(() => {
        setOverlay((current) => (current?.status === "success" ? null : current));
      }, SUCCESS_CLOSE_MS);
    } catch (error) {
      closeRecordingSocket(session);
      showOverlay({
        status: "error",
        title: "语音失败",
        transcript: session.transcript,
        error: error instanceof Error ? error.message : "录音处理失败",
      });
    }
  }, [onTodosCreated, showOverlay]);

  const startRecording = useCallback(async () => {
    if (recordingRef.current) return;
    stopRequestedRef.current = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      showOverlay({ status: "error", title: "语音失败", error: "当前浏览器不支持录音" });
      return;
    }

    try {
      showOverlay({ status: "preparing", message: "正在准备语音服务" });
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      const AudioContextClass =
        window.AudioContext ||
        (window as Window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext;
      if (!AudioContextClass) {
        throw new Error("当前浏览器不支持录音");
      }

      const context = new AudioContextClass();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const zeroGain = context.createGain();
      zeroGain.gain.value = 0;
      const socket = new WebSocket(voiceStreamUrl());
      socket.binaryType = "arraybuffer";

      const session = createRecordingSession({
        stream,
        context,
        source,
        processor,
        zeroGain,
        socket,
        stopRecording,
      });
      recordingRef.current = session;
      setRecording(true);
      attachVoiceSocketHandlers(session, showOverlay, recordingRef, () => setRecording(false));
      if (stopRequestedRef.current) {
        void stopRecording();
        return;
      }

      processor.onaudioprocess = (event) => {
        const input = new Float32Array(event.inputBuffer.getChannelData(0));
        const downsampled = downsampleBuffer(input, session.sampleRate, TARGET_SAMPLE_RATE);
        const pcm = floatTo16BitPcm(downsampled);
        appendPendingPcm(session, pcm);
      };
      source.connect(processor);
      processor.connect(zeroGain);
      zeroGain.connect(context.destination);
    } catch {
      const session = recordingRef.current;
      if (session) {
        recordingRef.current = null;
        setRecording(false);
        stopRecordingCapture(session);
        closeRecordingSocket(session);
      }
      showOverlay({ status: "error", title: "语音失败", error: "无法使用麦克风" });
    }
  }, [showOverlay, stopRecording]);

  useEffect(() => {
    const stop = () => {
      void stopRecording();
    };
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      clearSuccessTimer();
      const session = recordingRef.current;
      if (session) {
        stopRecordingCapture(session);
        closeRecordingSocket(session);
      }
    };
  }, [clearSuccessTimer, stopRecording]);

  return { recording, overlay, startRecording, stopRecording, closeOverlay };
}

function createRecordingSession({
  stream,
  context,
  source,
  processor,
  zeroGain,
  socket,
  stopRecording,
}: {
  stream: MediaStream;
  context: AudioContext;
  source: MediaStreamAudioSourceNode;
  processor: ScriptProcessorNode;
  zeroGain: GainNode;
  socket: WebSocket;
  stopRecording: () => Promise<void>;
}): RecordingSession {
  const session = {
    stream,
    context,
    source,
    processor,
    zeroGain,
    socket,
    socketReady: false,
    socketClosedByClient: false,
    pendingBytes: new Uint8Array(0),
    audioBytes: 0,
    transcript: "",
    finalTranscript: "",
    streamError: null,
    sampleRate: context.sampleRate,
    timeoutId: window.setTimeout(() => void stopRecording(), MAX_RECORDING_MS),
  } as RecordingSession;
  session.readyPromise = new Promise((resolve, reject) => {
    session.resolveReady = resolve;
    session.rejectReady = reject;
  });
  session.finalPromise = new Promise((resolve, reject) => {
    session.resolveFinal = resolve;
    session.rejectFinal = reject;
  });
  session.readyPromise.catch(() => null);
  session.finalPromise.catch(() => null);
  return session;
}

function attachVoiceSocketHandlers(
  session: RecordingSession,
  showOverlay: (overlay: VoiceOverlayState) => void,
  recordingRef: MutableRefObject<RecordingSession | null>,
  onStop: () => void,
) {
  session.socket.addEventListener("message", (event) => {
    let message: VoiceStreamMessage;
    try {
      message = JSON.parse(String(event.data)) as VoiceStreamMessage;
    } catch {
      failVoiceStream(session, new Error("语音服务返回格式异常"), showOverlay, recordingRef, onStop);
      return;
    }

    if (message.type === "ready") {
      session.socketReady = true;
      session.resolveReady?.();
      flushPendingPcm(session);
      if (recordingRef.current === session) {
        showOverlay({ status: "recording", transcript: session.transcript, message: "正在录音" });
      }
      return;
    }

    if (message.type === "partial") {
      session.transcript = message.transcript || session.transcript;
      if (recordingRef.current === session) {
        showOverlay({ status: "recording", transcript: session.transcript, message: "正在转文字" });
      }
      return;
    }

    if (message.type === "final") {
      session.finalTranscript = message.transcript || "";
      session.resolveFinal?.(session.finalTranscript);
      return;
    }

    if (message.type === "error") {
      failVoiceStream(session, new Error(message.error || "语音识别失败，未添加待办"), showOverlay, recordingRef, onStop);
    }
  });

  session.socket.addEventListener("error", () => {
    failVoiceStream(session, new Error("语音连接失败"), showOverlay, recordingRef, onStop);
  });

  session.socket.addEventListener("close", () => {
    if (!session.finalTranscript && !session.socketClosedByClient && !session.streamError) {
      failVoiceStream(session, new Error("语音连接已断开"), showOverlay, recordingRef, onStop);
    }
  });
}

function appendPendingPcm(session: RecordingSession, pcmBuffer: ArrayBuffer) {
  const bytes = new Uint8Array(pcmBuffer);
  session.audioBytes += bytes.byteLength;
  if (!session.pendingBytes.byteLength) {
    session.pendingBytes = bytes;
  } else {
    const merged = new Uint8Array(session.pendingBytes.byteLength + bytes.byteLength);
    merged.set(session.pendingBytes, 0);
    merged.set(bytes, session.pendingBytes.byteLength);
    session.pendingBytes = merged;
  }
  flushPendingPcm(session);
}

function flushPendingPcm(session: RecordingSession): boolean {
  if (!session.socketReady || session.socket.readyState !== WebSocket.OPEN) return false;
  if (!session.pendingBytes.byteLength) return false;

  const chunk = session.pendingBytes;
  session.pendingBytes = new Uint8Array(0);
  session.socket.send(chunk);
  return true;
}

async function finishVoiceStream(
  session: RecordingSession,
  showOverlay: (overlay: VoiceOverlayState) => void,
): Promise<string> {
  await waitWithTimeout(session.readyPromise, STREAM_READY_TIMEOUT_MS, "语音服务连接超时");
  flushPendingPcm(session);
  if (session.socket.readyState !== WebSocket.OPEN) {
    throw new Error("语音连接已断开");
  }
  showOverlay({
    status: "transcribing",
    transcript: session.transcript,
    message: "正在等待最终文本",
  });
  session.socket.send(JSON.stringify({ type: "end" }));
  const transcript = await waitWithTimeout(session.finalPromise, STREAM_RESULT_TIMEOUT_MS, "语音识别超时");
  if (!transcript) {
    throw new Error("语音未识别出有效文本");
  }
  return transcript;
}

async function createTodosFromTranscriptAndRefresh(
  transcript: string,
  showOverlay: (overlay: VoiceOverlayState) => void,
  onTodosCreated: () => Promise<void>,
) {
  showOverlay({ status: "parsing", transcript, message: "正在解析待办" });
  const result = await createTodosFromTranscript(transcript);
  if (!result.items.length) {
    showOverlay({
      status: "empty",
      transcript: result.transcript || transcript,
      message: result.message || "没有识别到需要新增的待办",
    });
    return;
  }

  await onTodosCreated();
  showOverlay({
    status: "success",
    transcript: result.transcript,
    items: result.items,
    message: `已添加 ${result.items.length} 项`,
  });
}

function failVoiceStream(
  session: RecordingSession,
  error: Error,
  showOverlay: (overlay: VoiceOverlayState) => void,
  recordingRef: MutableRefObject<RecordingSession | null>,
  onStop: () => void,
) {
  session.streamError = error;
  session.rejectReady?.(error);
  session.rejectFinal?.(error);
  if (recordingRef.current === session) {
    recordingRef.current = null;
    onStop();
    stopRecordingCapture(session);
    closeRecordingSocket(session);
    showOverlay({
      status: "error",
      title: "语音失败",
      transcript: session.transcript,
      error: error.message || "语音识别失败，未添加待办",
    });
  }
}

function stopRecordingCapture(session: RecordingSession) {
  if (session.captureStopped) return;
  session.captureStopped = true;
  window.clearTimeout(session.timeoutId);
  session.processor.disconnect();
  session.source.disconnect();
  session.zeroGain.disconnect();
  session.stream.getTracks().forEach((track) => track.stop());
  session.context.close().catch(() => null);
}

function closeRecordingSocket(session: RecordingSession) {
  if (session.socket.readyState === WebSocket.OPEN || session.socket.readyState === WebSocket.CONNECTING) {
    session.socketClosedByClient = true;
    session.socket.close();
  }
}

function waitWithTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timeoutId = 0;
  const timeout = new Promise<T>((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(message)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timeoutId));
}
