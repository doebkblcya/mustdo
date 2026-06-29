import type { FormEvent } from "react";

import type { TodoPublic } from "../api/types";
import { CheckIcon, CircleIcon, CloseIcon, EditIcon, SaveIcon, TrashIcon } from "../components/Icons";
import { formatDate } from "../utils/date";
import type { TodoEditValues } from "./types";

interface TodoItemProps {
  todo: TodoPublic;
  editing: boolean;
  editValues: TodoEditValues;
  compactMeta?: boolean;
  showDate?: boolean;
  onToggle: (todo: TodoPublic) => Promise<void>;
  onEdit: (todo: TodoPublic) => void;
  onDelete: (todo: TodoPublic) => Promise<void>;
  onSave: (todo: TodoPublic, values: TodoEditValues) => Promise<void>;
  onCancelEdit: () => void;
}

export function TodoItem({
  todo,
  editing,
  editValues,
  compactMeta = false,
  showDate = false,
  onToggle,
  onEdit,
  onDelete,
  onSave,
  onCancelEdit,
}: TodoItemProps) {
  const done = todo.status === "done";
  const metaParts: string[] = [];
  if (showDate) metaParts.push(formatDate(todo.due_date));
  if (!compactMeta && todo.due_time) metaParts.push(todo.due_time);
  const meta = metaParts.join(" ");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await onSave(todo, {
      content: String(form.get("content") || ""),
      due_date: String(form.get("due_date") || ""),
      due_time: String(form.get("due_time") || ""),
    });
  }

  return (
    <article className={`todo-item ${done ? "done" : ""}`} data-todo-id={todo.id}>
      <button
        className={`status-button ${done ? "is-done" : ""}`}
        type="button"
        title={done ? "标记未完成" : "标记完成"}
        aria-label={done ? "标记未完成" : "标记完成"}
        onClick={() => void onToggle(todo)}
      >
        {done ? <CheckIcon /> : <CircleIcon />}
      </button>
      <div className="todo-content">
        <div className="todo-title">{todo.content}</div>
        {meta ? <div className="todo-meta">{meta}</div> : null}
      </div>
      <div className="todo-actions">
        <button className="icon-button" type="button" title="编辑" aria-label="编辑" onClick={() => onEdit(todo)}>
          <EditIcon />
        </button>
        <button
          className="icon-button icon-danger"
          type="button"
          title="删除"
          aria-label="删除"
          onClick={() => void onDelete(todo)}
        >
          <TrashIcon />
        </button>
      </div>
      {editing ? (
        <form className="todo-edit" onSubmit={handleSubmit}>
          <input className="field" name="content" defaultValue={editValues.content} required maxLength={200} />
          <input className="field" name="due_date" type="date" defaultValue={editValues.due_date} required />
          <input className="field" name="due_time" type="time" defaultValue={editValues.due_time} />
          <button className="icon-button" type="submit" title="保存" aria-label="保存">
            <SaveIcon />
          </button>
          <button className="icon-button" type="button" title="取消" aria-label="取消" onClick={onCancelEdit}>
            <CloseIcon />
          </button>
        </form>
      ) : null}
    </article>
  );
}
