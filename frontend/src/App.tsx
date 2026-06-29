import { useCallback, useEffect, useState } from "react";

import { getMe, listTodos, login, logout, register } from "./api/client";
import type { TodoListResponse, UserPublic } from "./api/types";
import { AuthPage, type AuthMode } from "./auth/AuthPage";
import { TodoDashboard } from "./todos/TodoDashboard";
import type { TodoEditValues, ViewKey } from "./todos/types";
import { VoiceButton } from "./voice/VoiceButton";
import { VoiceOverlay } from "./voice/VoiceOverlay";
import { useVoiceRecorder } from "./voice/useVoiceRecorder";

export function App() {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authError, setAuthError] = useState("");
  const [todos, setTodos] = useState<TodoListResponse | null>(null);
  const [activeView, setActiveView] = useState<ViewKey>("today");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<Record<number, TodoEditValues>>({});

  const loadTodos = useCallback(async () => {
    setTodos(await listTodos());
  }, []);

  const voice = useVoiceRecorder(loadTodos);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const currentUser = await getMe();
        if (cancelled) return;
        setUser(currentUser);
        setTodos(await listTodos());
      } catch {
        if (!cancelled) setUser(null);
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleAuthSubmit(payload: Record<string, FormDataEntryValue>) {
    setAuthError("");
    try {
      const result = authMode === "register" ? await register(payload) : await login(payload);
      setUser(result.user);
      setAuthError("");
      await loadTodos();
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "请求失败");
    }
  }

  async function handleLogout() {
    await logout();
    setUser(null);
    setTodos(null);
  }

  function handleEditingChange(id: number | null, values?: TodoEditValues) {
    setEditingId(id);
    if (id === null) {
      setEditValues({});
      return;
    }
    setEditValues((current) => ({ ...current, [id]: values || current[id] }));
  }

  if (!user) {
    return (
      <AuthPage
        mode={authMode}
        error={authError}
        onModeChange={(mode) => {
          setAuthMode(mode);
          setAuthError("");
        }}
        onSubmit={handleAuthSubmit}
      />
    );
  }

  return (
    <TodoDashboard
      user={user}
      todos={todos}
      activeView={activeView}
      editingId={editingId}
      editValues={editValues}
      onLogout={handleLogout}
      onLoadTodos={loadTodos}
      onActiveViewChange={(view) => {
        setActiveView(view);
        setEditingId(null);
      }}
      onEditingChange={handleEditingChange}
      voiceSlot={
        <VoiceButton
          recording={voice.recording}
          onStart={voice.startRecording}
          onStop={voice.stopRecording}
        />
      }
      overlaySlot={<VoiceOverlay overlay={voice.overlay} onClose={voice.closeOverlay} />}
    />
  );
}
