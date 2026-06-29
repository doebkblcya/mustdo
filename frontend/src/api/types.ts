export interface UserPublic {
  id: number;
  username: string;
}

export interface AuthResponse {
  user: UserPublic;
}

export interface TodoPublic {
  id: number;
  content: string;
  due_date: string;
  due_time: string | null;
  status: "pending" | "done";
  created_at: string;
  updated_at: string;
}

export interface TodoGroups {
  today: TodoPublic[];
  tomorrow: TodoPublic[];
  upcoming: TodoPublic[];
}

export interface TodoListResponse {
  today_date: string;
  tomorrow_date: string;
  groups: TodoGroups;
}

export interface TodoUpdateRequest {
  content?: string | null;
  due_date?: string | null;
  due_time?: string | null;
  status?: "pending" | "done";
}

export interface AiCreateResponse {
  transcript: string;
  items: TodoPublic[];
  message?: string | null;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  details: unknown;
}

export interface ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
}
