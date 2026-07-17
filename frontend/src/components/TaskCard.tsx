import { Calendar, CheckCircle } from "lucide-react";
import { format } from "date-fns";
import { StatusBadge } from "./StatusBadge";
import type { Task } from "../api/types";

interface TaskCardProps {
  task: Task;
  onDragStart?: (e: React.DragEvent, taskId: string) => void;
  onClick?: () => void;
  selected?: boolean;
  selectMode?: boolean;
  onToggleSelect?: (id: string) => void;
}

const PRIORITY_COLORS: Record<string, string> = {
  low: "bg-slate-500",
  medium: "bg-blue-500",
  high: "bg-orange-500",
  urgent: "bg-red-500",
};

export function TaskCard({
  task,
  onDragStart,
  onClick,
  selected = false,
  selectMode = false,
  onToggleSelect,
}: TaskCardProps) {
  const created = task.created_at ? new Date(task.created_at) : null;

  const handleCardClick = () => {
    if (selectMode && onToggleSelect) {
      onToggleSelect(task.id);
      return;
    }
    onClick?.();
  };

  return (
    <div
      draggable={!selectMode && !!onDragStart}
      onDragStart={(e) => onDragStart?.(e, task.id)}
      onClick={handleCardClick}
      className={`cursor-grab rounded-lg border p-3 transition active:cursor-grabbing ${
        selected
          ? "border-bb-accent bg-bb-accent/10 ring-1 ring-bb-accent"
          : "border-bb-border bg-bb-card hover:border-bb-accent/50"
      } ${selectMode ? "cursor-pointer" : ""}`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        {selectMode && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleSelect?.(task.id);
            }}
            className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition ${
              selected ? "border-bb-accent bg-bb-accent text-white" : "border-bb-border"
            }`}
            aria-label={selected ? "Deselect task" : "Select task"}
          >
            {selected && <CheckCircle size={12} />}
          </button>
        )}
        <h4 className="flex-1 text-sm font-medium">{task.title}</h4>
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

      <div className="flex items-center justify-between text-xs text-bb-muted">
        <StatusBadge status={task.status} />
        <div className="flex items-center gap-2">
          {task.due_date && (
            <span className="flex items-center gap-1">
              <Calendar size={10} />
              {format(new Date(task.due_date), "MMM d")}
            </span>
          )}
          {created && (
            <span className="text-bb-muted/70" title={`Created ${created.toLocaleString()}`}>
              {format(created, "MMM d")}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
