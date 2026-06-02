import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, CheckSquare, FileText, Upload, List, LayoutTemplate } from "lucide-react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { StatusBadge } from "../components/StatusBadge";
import { TaskCard } from "../components/TaskCard";
import { TranscriptCard } from "../components/TranscriptCard";
import { KanbanBoard } from "../components/KanbanBoard";
import { useProject, useTasks, useTranscripts } from "../hooks/useApi";

const COLORS = ["#3b82f6", "#f59e0b", "#22c55e", "#ef4444"];

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const [taskView, setTaskView] = useState<"list" | "kanban">("kanban");
  const { data: project, isLoading: projectLoading } = useProject(id || "");
  const { data: tasksData } = useTasks({ project_id: id });
  const { data: transcriptsData } = useTranscripts({ project_name: project?.name });

  const tasks = tasksData?.items || [];
  const transcripts = transcriptsData?.items || [];

  const statusCounts = {
    todo: tasks.filter((t) => t.status === "todo").length,
    in_progress: tasks.filter((t) => t.status === "in_progress").length,
    completed: tasks.filter((t) => t.status === "completed").length,
    abandoned: tasks.filter((t) => t.status === "abandoned").length,
  };

  const chartData = Object.entries(statusCounts)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({ name: name.replace("_", " "), value }));

  if (projectLoading || !project) {
    return (
      <div className="space-y-4">
        <div className="h-6 w-48 animate-pulse rounded bg-slate-700" />
        <div className="h-32 animate-pulse rounded-lg bg-bb-card" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link
          to="/projects"
          className="rounded p-1 text-bb-muted hover:bg-bb-border hover:text-bb-text"
        >
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold">{project.name}</h1>
          {project.description && (
            <p className="text-sm text-bb-muted">{project.description}</p>
          )}
        </div>
        <StatusBadge status={project.status} />
        <Link
          to="/todoist"
          className="flex items-center gap-1.5 rounded-md bg-bb-accent/20 px-3 py-1.5 text-xs font-medium text-bb-accent transition hover:bg-bb-accent/30"
        >
          <Upload size={12} /> Export
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <h3 className="mb-3 text-sm font-semibold">Task Status</h3>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie data={chartData} cx="50%" cy="50%" innerRadius={50} outerRadius={70} dataKey="value" nameKey="name">
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1e293b",
                    border: "1px solid #334155",
                    borderRadius: "6px",
                    fontSize: "12px",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="py-8 text-center text-xs text-bb-muted">No tasks</div>
          )}
        </div>

        <div className="rounded-lg border border-bb-border bg-bb-card p-4 lg:col-span-2">
          <h3 className="mb-3 text-sm font-semibold">Details</h3>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-bb-muted">Confidence:</span>{" "}
              <span className="font-medium">{Math.round(project.confidence * 100)}%</span>
            </div>
            <div>
              <span className="text-bb-muted">Tasks:</span>{" "}
              <span className="font-medium">{project.task_count}</span>
            </div>
            <div>
              <span className="text-bb-muted">Transcripts:</span>{" "}
              <span className="font-medium">{project.transcript_count}</span>
            </div>
            <div>
              <span className="text-bb-muted">Last Activity:</span>{" "}
              <span className="font-medium">
                {project.last_activity_at
                  ? new Date(project.last_activity_at).toLocaleDateString()
                  : "Never"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <CheckSquare size={16} /> Tasks ({tasks.length})
          </h2>
          <div className="flex rounded-md border border-bb-border">
            <button
              onClick={() => setTaskView("kanban")}
              className={`flex items-center gap-1 rounded-l-md px-3 py-1.5 text-xs transition ${
                taskView === "kanban" ? "bg-bb-accent/20 text-bb-accent" : "text-bb-muted hover:text-bb-text"
              }`}
            >
              <LayoutTemplate size={12} /> Kanban
            </button>
            <button
              onClick={() => setTaskView("list")}
              className={`flex items-center gap-1 rounded-r-md px-3 py-1.5 text-xs transition ${
                taskView === "list" ? "bg-bb-accent/20 text-bb-accent" : "text-bb-muted hover:text-bb-text"
              }`}
            >
              <List size={12} /> List
            </button>
          </div>
        </div>

        {taskView === "kanban" ? (
          <KanbanBoard tasks={tasks} />
        ) : (
          <div className="space-y-2">
            {tasks.length === 0 ? (
              <div className="py-4 text-center text-xs text-bb-muted">No tasks</div>
            ) : (
              tasks.map((t) => <TaskCard key={t.id} task={t} />)
            )}
          </div>
        )}
      </div>

      <div>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
          <FileText size={16} /> Transcripts ({transcripts.length})
        </h2>
        <div className="space-y-2">
          {transcripts.length === 0 ? (
            <div className="py-4 text-center text-xs text-bb-muted">No transcripts</div>
          ) : (
            transcripts.map((t) => <TranscriptCard key={t.id} transcript={t} />)
          )}
        </div>
      </div>
    </div>
  );
}
