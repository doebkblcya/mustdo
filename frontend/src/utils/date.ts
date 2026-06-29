import type { TodoPublic } from "../api/types";

export function todayString(): string {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date()).map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00+08:00`);
  return date.toLocaleDateString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    weekday: "short",
  });
}

export function isVisibleTodo(todo: TodoPublic): boolean {
  return todo.due_date >= todayString();
}
