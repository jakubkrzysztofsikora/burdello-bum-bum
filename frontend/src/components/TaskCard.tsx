import { Calendar } from "lucide-react";
import { format } from "date-fns";
import { StatusBadge } from "./StatusBadge";
import type { Task } from "../api/types";

interface TaskCardProps {
  task: Task;
  onDragStart?: (e: React.DragEvent, taskId: string) => void;
  onClick?: () => void;
}

const PRIORITY_COLORS: Record<string, string> = {
  low: "bg-slate-500",
  medium: "bg-blue-500",
  high: "bg-orange-500",
  urgent: "bg-red-500",
};

export function TaskCard({ task, onDragStart, onClick }: TaskCardProps) {
  return (
    <div
      draggable={!!onDragStart}
      onDragStart={(e) => onDragStart?.(e, task.id)}
      onClick={onClick}
      className="cursor-grab rounded-lg border border-bb-border bg-bb-card p-3 transition hover:border-bb-accent/50 active:cursor-grabbing"
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h4 className="text-sm font-medium">{task.title}</h4>
        <div className={`h-2 w-2 shrink-0 rounded-full ${PRIORITY_COLORS[task.priority] || "bg-slate-500"}`} title={task.priority} />
      </div>

      {task.description && (
        <p className="mb-2 line-clamp-2 text-xs text-bb-muted">{task.description}</p>
      )}

      <div className="mb-2">
        <div className="flex justify-between text-xs text-bb-muted">
          <span>Confidence</span>
          <span>{Math.round(task.confidence * 100)}%</span>
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-bb-dark">
          <div
            className="h-full rounded-full bg-bb-success transition-all"
            style={{ width: `${task.confidence * 100}%` }}
          />
        </div>
      </div>

      <div className="flex items-center justify-between">
        <StatusBadge status={task.status} />
        {task.due_date && (
          <span className="flex items-center gap-1 text-xs text-bb-muted">
            <Calendar size={10} />
            {format(new Date(task.due_date), "MMM d")}
          </span>
        )}
      </div>
    </div>
  );
}
