import { useState } from "react";
import { List, LayoutTemplate, ArrowUpDown } from "lucide-react";
import { TaskCard } from "../components/TaskCard";
import { KanbanBoard } from "../components/KanbanBoard";
import { FilterBar } from "../components/FilterBar";
import { useTasks } from "../hooks/useApi";
import { useAppStore } from "../stores/useAppStore";

type SortField = "priority" | "status" | "due_date";

export function Tasks() {
  const { filters } = useAppStore();
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [sort, setSort] = useState<SortField>("priority");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const { data, isLoading } = useTasks({
    ...filters,
    sort,
    order,
    limit: 100,
  });

  const tasks = data?.items || [];

  const toggleSort = (field: SortField) => {
    if (sort === field) {
      setOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSort(field);
      setOrder("desc");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Tasks</h1>
        <div className="flex rounded-md border border-bb-border">
          <button
            onClick={() => setView("kanban")}
            className={`flex items-center gap-1 rounded-l-md px-3 py-1.5 text-xs transition ${
              view === "kanban" ? "bg-bb-accent/20 text-bb-accent" : "text-bb-muted hover:text-bb-text"
            }`}
          >
            <LayoutTemplate size={12} /> Kanban
          </button>
          <button
            onClick={() => setView("list")}
            className={`flex items-center gap-1 rounded-r-md px-3 py-1.5 text-xs transition ${
              view === "list" ? "bg-bb-accent/20 text-bb-accent" : "text-bb-muted hover:text-bb-text"
            }`}
          >
            <List size={12} /> List
          </button>
        </div>
      </div>

      <FilterBar />

      <div className="flex items-center gap-2 text-xs">
        <span className="text-bb-muted">Sort:</span>
        {(["priority", "status", "due_date"] as SortField[]).map((f) => (
          <button
            key={f}
            onClick={() => toggleSort(f)}
            className={`flex items-center gap-1 rounded px-2 py-1 transition ${
              sort === f ? "bg-bb-accent/20 text-bb-accent" : "text-bb-muted hover:text-bb-text"
            }`}
          >
            {f.replace("_", " ")}
            {sort === f && <ArrowUpDown size={10} />}
          </button>
        ))}
        <span className="ml-auto text-bb-muted">{tasks.length} tasks</span>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg bg-bb-card" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="py-12 text-center text-sm text-bb-muted">No tasks found</div>
      ) : view === "kanban" ? (
        <KanbanBoard tasks={tasks} />
      ) : (
        <div className="space-y-2">
          {tasks.map((t) => (
            <TaskCard key={t.id} task={t} />
          ))}
        </div>
      )}
    </div>
  );
}
