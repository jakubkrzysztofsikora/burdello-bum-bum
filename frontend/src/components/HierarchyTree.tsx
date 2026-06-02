import { useState } from "react";
import { ChevronRight, ChevronDown, FolderKanban, CheckSquare, FileText } from "lucide-react";
import { Link } from "react-router-dom";
import type { Project, Task, Transcript } from "../api/types";

interface HierarchyTreeProps {
  projects: Project[];
  tasks?: Task[];
  transcripts?: Transcript[];
}

export function HierarchyTree({ projects, tasks = [], transcripts = [] }: HierarchyTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-1">
      {projects.map((project) => {
        const isExpanded = expanded.has(project.id);
        const projectTasks = tasks.filter((t) => t.project_id === project.id);
        const projectTranscripts = transcripts.filter((t) => t.project_name === project.name);

        return (
          <div key={project.id} className="rounded-lg border border-bb-border bg-bb-card">
            <button
              onClick={() => toggle(project.id)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-bb-border/50"
            >
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <FolderKanban size={14} className="text-purple-400" />
              <span className="flex-1 text-sm font-medium">{project.name}</span>
              <span className="flex items-center gap-2 text-xs text-bb-muted">
                <span className="flex items-center gap-1"><CheckSquare size={10} /> {projectTasks.length}</span>
                <span className="flex items-center gap-1"><FileText size={10} /> {projectTranscripts.length}</span>
              </span>
            </button>

            {isExpanded && (
              <div className="border-t border-bb-border">
                {projectTasks.length === 0 && projectTranscripts.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-bb-muted">No items</div>
                ) : (
                  <div className="space-y-0.5 py-1">
                    {projectTasks.map((task) => (
                      <div key={task.id} className="flex items-center gap-2 px-6 py-1.5 text-sm text-bb-muted hover:text-bb-text">
                        <CheckSquare size={12} className="text-green-400" />
                        <span className="flex-1 truncate">{task.title}</span>
                        <span className="text-xs capitalize">{task.status.replace("_", " ")}</span>
                      </div>
                    ))}
                    {projectTranscripts.map((tx) => (
                      <Link
                        key={tx.id}
                        to={`/transcripts/${tx.id}`}
                        className="flex items-center gap-2 px-6 py-1.5 text-sm text-bb-muted hover:text-bb-text"
                      >
                        <FileText size={12} className="text-blue-400" />
                        <span className="flex-1 truncate">{tx.project_name || tx.id.slice(0, 8)}</span>
                        <span className="text-xs">{tx.message_count} msgs</span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
