import { TaskCard } from "./TaskCard";
import { useUpdateTaskStatus } from "../hooks/useApi";
import type { Task } from "../api/types";

interface KanbanBoardProps {
  tasks: Task[];
}

const COLUMNS: { key: Task["status"]; label: string }[] = [
  { key: "todo", label: "Todo" },
  { key: "in_progress", label: "In Progress" },
  { key: "done", label: "Done" },
  { key: "cancelled", label: "Cancelled" },
];

export function KanbanBoard({ tasks }: KanbanBoardProps) {
  const updateStatus = useUpdateTaskStatus();

  const handleDragStart = (e: React.DragEvent, taskId: string) => {
    e.dataTransfer.setData("taskId", taskId);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent, status: Task["status"]) => {
    e.preventDefault();
    const taskId = e.dataTransfer.getData("taskId");
    if (taskId) {
      updateStatus.mutate({ id: taskId, status });
    }
  };

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      {COLUMNS.map((col) => {
        const colTasks = tasks.filter((t) => t.status === col.key);
        return (
          <div
            key={col.key}
            onDragOver={handleDragOver}
            onDrop={(e) => handleDrop(e, col.key)}
            className="flex max-h-[calc(100vh-220px)] flex-col rounded-lg border border-bb-border bg-bb-dark/50"
          >
            <div className="flex items-center justify-between border-b border-bb-border px-3 py-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-bb-muted">
                {col.label}
              </span>
              <span className="rounded-full bg-bb-border px-2 py-0.5 text-xs text-bb-muted">
                {colTasks.length}
              </span>
            </div>
            <div className="flex-1 space-y-2 overflow-auto p-2">
              {colTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onDragStart={handleDragStart}
                />
              ))}
              {colTasks.length === 0 && (
                <div className="py-8 text-center text-xs text-bb-muted">
                  No tasks
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
