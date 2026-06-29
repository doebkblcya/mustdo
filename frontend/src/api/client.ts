import type {
  AiCreateResponse,
  ApiError,
  ApiErrorPayload,
  AuthResponse,
  TodoListResponse,
  TodoUpdateRequest,
  UserPublic,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export function voiceStreamUrl(): string {
  if (API_BASE_URL) {
    const url = new URL(API_BASE_URL);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/api/voice/stream";
    url.search = "";
    return url.toString();
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/voice/stream`;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 204) return null as T;

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw createApiError(response.status, normalizeApiError(data));
  }
  return data as T;
}

export async function getMe(): Promise<UserPublic> {
  return api<UserPublic>("/api/me");
}

export async function login(payload: Record<string, FormDataEntryValue>): Promise<AuthResponse> {
  return api<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function register(payload: Record<string, FormDataEntryValue>): Promise<AuthResponse> {
  return api<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function logout(): Promise<void> {
  await api<null>("/api/auth/logout", { method: "POST" }).catch(() => null);
}

export async function listTodos(): Promise<TodoListResponse> {
  return api<TodoListResponse>("/api/todos");
}

export async function updateTodo(id: number, payload: TodoUpdateRequest): Promise<void> {
  await api(`/api/todos/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteTodo(id: number): Promise<void> {
  await api<null>(`/api/todos/${id}`, { method: "DELETE" });
}

export async function createTodosFromTranscript(transcript: string): Promise<AiCreateResponse> {
  return api<AiCreateResponse>("/api/todos/ai", {
    method: "POST",
    body: JSON.stringify({ transcript }),
  });
}

function createApiError(status: number, payload: ApiErrorPayload): ApiError {
  const error = new Error(payload.message) as ApiError;
  error.status = status;
  error.code = payload.code;
  error.details = payload.details;
  return error;
}

function normalizeApiError(data: unknown): ApiErrorPayload {
  if (isObject(data) && typeof data.code === "string" && typeof data.message === "string") {
    return {
      code: data.code,
      message: data.message,
      details: "details" in data ? data.details : null,
    };
  }

  const detail = isObject(data) && "detail" in data ? data.detail : data;
  return {
    code: "api_error",
    message: formatLegacyApiError(detail),
    details: Array.isArray(detail) ? detail : null,
  };
}

function formatLegacyApiError(detail: unknown): string {
  if (!detail) return "请求失败";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (!isObject(item)) return "参数不合法";
        const loc = Array.isArray(item.loc) ? item.loc : [];
        const field = loc.length ? String(loc[loc.length - 1]) : "";
        const message = typeof item.msg === "string" ? item.msg : "参数不合法";
        return field ? `${field}: ${message}` : message;
      })
      .join("；");
  }
  if (isObject(detail)) {
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.msg === "string") return detail.msg;
    return JSON.stringify(detail);
  }
  return String(detail);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
