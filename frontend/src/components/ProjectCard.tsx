import { Link } from "react-router-dom";
import { FileText, CheckSquare, Clock } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { StatusBadge } from "./StatusBadge";
import type { Project } from "../api/types";

interface ProjectCardProps {
  project: Project;
}

export function ProjectCard({ project }: ProjectCardProps) {
  const completedTasks = 0;
  const totalTasks = project.task_count || 0;
  const progress = totalTasks > 0 ? (completedTasks / totalTasks) * 100 : 0;

  return (
    <Link
      to={`/projects/${project.id}`}
      className="group block rounded-lg border border-bb-border bg-bb-card p-4 transition hover:border-bb-accent/50"
    >
      <div className="mb-2 flex items-start justify-between">
        <h3 className="font-semibold text-bb-text transition group-hover:text-bb-accent">
          {project.name}
        </h3>
        <StatusBadge status={project.status} />
      </div>

      {project.description && (
        <p className="mb-3 line-clamp-2 text-xs text-bb-muted">{project.description}</p>
      )}

      <div className="mb-2">
        <div className="mb-1 flex justify-between text-xs text-bb-muted">
          <span>Progress</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-bb-dark">
          <div
            className="h-full rounded-full bg-bb-accent transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-bb-muted">
        <span className="flex items-center gap-1">
          <CheckSquare size={12} /> {totalTasks}
        </span>
        <span className="flex items-center gap-1">
          <FileText size={12} /> {project.transcript_count || 0}
        </span>
        {project.last_activity_at && (
          <span className="ml-auto flex items-center gap-1">
            <Clock size={12} />
            {formatDistanceToNow(new Date(project.last_activity_at), { addSuffix: true })}
          </span>
        )}
      </div>
    </Link>
  );
}
