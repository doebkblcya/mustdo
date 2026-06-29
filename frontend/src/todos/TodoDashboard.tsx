import type { CSSProperties, ReactNode } from "react";

import type { TodoListResponse, TodoPublic, UserPublic } from "../api/types";
import { deleteTodo, updateTodo } from "../api/client";
import { formatDate, isVisibleTodo, todayString } from "../utils/date";
import { TodoItem } from "./TodoItem";
import type { TodoEditValues, ViewConfig, ViewKey } from "./types";
import { viewConfigs } from "./types";

interface TodoDashboardProps {
  user: UserPublic;
  todos: TodoListResponse | null;
  activeView: ViewKey;
  editingId: number | null;
  editValues: Record<number, TodoEditValues>;
  voiceSlot: ReactNode;
  overlaySlot: ReactNode;
  onLogout: () => Promise<void>;
  onLoadTodos: () => Promise<void>;
  onActiveViewChange: (view: ViewKey) => void;
  onEditingChange: (id: number | null, values?: TodoEditValues) => void;
}

const emptyTodos: TodoListResponse = {
  today_date: todayString(),
  tomorrow_date: "",
  groups: { today: [], tomorrow: [], upcoming: [] },
};

export function TodoDashboard({
  user,
  todos,
  activeView,
  editingId,
  editValues,
  voiceSlot,
  overlaySlot,
  onLogout,
  onLoadTodos,
  onActiveViewChange,
  onEditingChange,
}: TodoDashboardProps) {
  const resolvedTodos = todos || emptyTodos;
  const views = viewConfigs(resolvedTodos);
  const current = views.find((view) => view.key === activeView) || views[0];

  async function handleToggle(todo: TodoPublic) {
    await updateTodo(todo.id, { status: todo.status === "done" ? "pending" : "done" });
    await onLoadTodos();
  }

  async function handleSave(todo: TodoPublic, values: TodoEditValues) {
    await updateTodo(todo.id, {
      content: values.content,
      due_date: values.due_date,
      due_time: values.due_time || null,
    });
    onEditingChange(null);
    await onLoadTodos();
  }

  async function handleDelete(todo: TodoPublic) {
    if (!window.confirm("删除这条待办？")) return;
    await deleteTodo(todo.id);
    await onLoadTodos();
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <h1>Todo Analyzer</h1>
        </div>
        <div className="user-actions">
          <span className="user-chip">{user.username}</span>
          <button className="secondary-button" type="button" onClick={() => void onLogout()}>
            登出
          </button>
        </div>
      </header>
      <ViewTabs views={views} activeView={activeView} onActiveViewChange={onActiveViewChange} />
      <SchedulePage
        view={current}
        editingId={editingId}
        editValues={editValues}
        onToggle={handleToggle}
        onEdit={(todo) =>
          onEditingChange(todo.id, {
            content: todo.content,
            due_date: todo.due_date,
            due_time: todo.due_time || "",
          })
        }
        onDelete={handleDelete}
        onSave={handleSave}
        onCancelEdit={() => onEditingChange(null)}
      />
      {voiceSlot}
      {overlaySlot}
    </main>
  );
}

function ViewTabs({
  views,
  activeView,
  onActiveViewChange,
}: {
  views: ViewConfig[];
  activeView: ViewKey;
  onActiveViewChange: (view: ViewKey) => void;
}) {
  const activeIndex = views.findIndex((view) => view.key === activeView);
  return (
    <nav className="view-tabs" aria-label="待办时间范围" style={{ "--active-index": Math.max(activeIndex, 0) } as CSSProperties}>
      <span className="view-tab-indicator" aria-hidden="true" />
      {views.map((view) => {
        const count = view.items.filter(isVisibleTodo).length;
        const active = view.key === activeView;
        const label = view.key === "upcoming" ? `${count} 项` : view.dateLabel ? formatDate(view.dateLabel) : "";
        return (
          <button
            key={view.key}
            className={`view-tab ${active ? "active" : ""}`}
            type="button"
            aria-pressed={active}
            onClick={() => onActiveViewChange(view.key)}
          >
            <span className="view-tab-title">{view.title}</span>
            <span className="view-tab-meta">{label}</span>
          </button>
        );
      })}
    </nav>
  );
}

function SchedulePage({
  view,
  editingId,
  editValues,
  onToggle,
  onEdit,
  onDelete,
  onSave,
  onCancelEdit,
}: {
  view: ViewConfig;
  editingId: number | null;
  editValues: Record<number, TodoEditValues>;
  onToggle: (todo: TodoPublic) => Promise<void>;
  onEdit: (todo: TodoPublic) => void;
  onDelete: (todo: TodoPublic) => Promise<void>;
  onSave: (todo: TodoPublic, values: TodoEditValues) => Promise<void>;
  onCancelEdit: () => void;
}) {
  const visible = view.items.filter(isVisibleTodo);
  const untimed = visible.filter((todo) => !todo.due_time);
  const timed = visible.filter((todo) => todo.due_time);
  const dateLabel = view.key === "upcoming" ? `${visible.length} 项` : view.dateLabel ? formatDate(view.dateLabel) : "";

  return (
    <section className="schedule-page" data-view-panel={view.key}>
      <div className="schedule-header">
        <div>
          <h2 className="schedule-title">{view.title}</h2>
          <div className="schedule-date">{dateLabel}</div>
        </div>
        <span className="schedule-count">{visible.length} 项</span>
      </div>
      <div className="schedule-content">
        {visible.length ? (
          <>
            <TodoSection
              items={untimed}
              label="无具体时间"
              view={view}
              editingId={editingId}
              editValues={editValues}
              onToggle={onToggle}
              onEdit={onEdit}
              onDelete={onDelete}
              onSave={onSave}
              onCancelEdit={onCancelEdit}
            />
            <TimelineSection
              items={timed}
              view={view}
              editingId={editingId}
              editValues={editValues}
              onToggle={onToggle}
              onEdit={onEdit}
              onDelete={onDelete}
              onSave={onSave}
              onCancelEdit={onCancelEdit}
            />
          </>
        ) : (
          <div className="empty large">暂无待办</div>
        )}
      </div>
    </section>
  );
}

function TodoSection({
  items,
  label,
  view,
  editingId,
  editValues,
  onToggle,
  onEdit,
  onDelete,
  onSave,
  onCancelEdit,
}: {
  items: TodoPublic[];
  label: string;
  view: ViewConfig;
  editingId: number | null;
  editValues: Record<number, TodoEditValues>;
  onToggle: (todo: TodoPublic) => Promise<void>;
  onEdit: (todo: TodoPublic) => void;
  onDelete: (todo: TodoPublic) => Promise<void>;
  onSave: (todo: TodoPublic, values: TodoEditValues) => Promise<void>;
  onCancelEdit: () => void;
}) {
  if (!items.length) return null;
  return (
    <section className="untimed-section">
      <div className="section-label">
        <span>{label}</span>
        <span>{items.length} 项</span>
      </div>
      <div className="untimed-list">
        {items.map((todo) => (
          <TodoItem
            key={todo.id}
            todo={todo}
            editing={editingId === todo.id}
            editValues={editValues[todo.id] || { content: todo.content, due_date: todo.due_date, due_time: todo.due_time || "" }}
            showDate={view.key === "upcoming"}
            onToggle={onToggle}
            onEdit={onEdit}
            onDelete={onDelete}
            onSave={onSave}
            onCancelEdit={onCancelEdit}
          />
        ))}
      </div>
    </section>
  );
}

function TimelineSection(props: Omit<Parameters<typeof TodoSection>[0], "label">) {
  const { items, view, editingId, editValues, onToggle, onEdit, onDelete, onSave, onCancelEdit } = props;
  if (!items.length) return null;
  return (
    <section className="timeline-section">
      <div className="section-label">
        <span>时间线</span>
        <span>{items.length} 项</span>
      </div>
      <div className="timeline">
        {items.map((todo) => (
          <div className="timeline-row" key={todo.id}>
            <div className="timeline-marker">
              {view.key === "upcoming" ? <span>{formatDate(todo.due_date)}</span> : null}
              <strong>{todo.due_time}</strong>
            </div>
            <div className="timeline-node" aria-hidden="true" />
            <div className="timeline-card">
              <TodoItem
                todo={todo}
                editing={editingId === todo.id}
                editValues={editValues[todo.id] || { content: todo.content, due_date: todo.due_date, due_time: todo.due_time || "" }}
                compactMeta
                showDate={view.key === "upcoming"}
                onToggle={onToggle}
                onEdit={onEdit}
                onDelete={onDelete}
                onSave={onSave}
                onCancelEdit={onCancelEdit}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
