import type { TodoListResponse, TodoPublic } from "../api/types";

export type ViewKey = "today" | "tomorrow" | "upcoming";

export interface ViewConfig {
  key: ViewKey;
  title: string;
  dateLabel: string;
  items: TodoPublic[];
}

export interface TodoEditValues {
  content: string;
  due_date: string;
  due_time: string;
}

export function viewConfigs(todos: TodoListResponse): ViewConfig[] {
  return [
    {
      key: "today",
      title: "今天",
      dateLabel: todos.today_date,
      items: todos.groups.today,
    },
    {
      key: "tomorrow",
      title: "明天",
      dateLabel: todos.tomorrow_date,
      items: todos.groups.tomorrow,
    },
    {
      key: "upcoming",
      title: "后续",
      dateLabel: "",
      items: todos.groups.upcoming,
    },
  ];
}
