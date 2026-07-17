import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, CheckSquare, FileText, Upload, List, LayoutTemplate, Bookmark, CheckCheck, X } from "lucide-react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { StatusBadge } from "../components/StatusBadge";
import { TaskCard } from "../components/TaskCard";
import { TranscriptCard } from "../components/TranscriptCard";
import { KanbanBoard } from "../components/KanbanBoard";
import { useProject, useTasks, useTranscripts, useBookmarks, useBatchUpdateTaskStatus } from "../hooks/useApi";
import { useAppStore } from "../stores/useAppStore";

const COLORS = ["#3b82f6", "#f59e0b", "#22c55e", "#ef4444"];

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const [taskView, setTaskView] = useState<"list" | "kanban">("kanban");
  const { data: project, isLoading: projectLoading } = useProject(id || "");
  const { data: tasksData } = useTasks({ project_id: id });
  const { data: transcriptsData } = useTranscripts({ project_name: project?.name });
  const { data: bookmarksData } = useBookmarks({ project_id: id, limit: 500 });

  const tasks = tasksData?.items || [];
  const transcripts = transcriptsData?.items || [];
  const bookmarks = bookmarksData?.items || [];

  const selectMode = useAppStore((s) => s.selectMode);
  const setSelectMode = useAppStore((s) => s.setSelectMode);
  const selectedTaskIds = useAppStore((s) => s.selectedTaskIds);
  const toggleTaskSelected = useAppStore((s) => s.toggleTaskSelected);
  const setSelectedTasks = useAppStore((s) => s.setSelectedTasks);
  const clearSelectedTasks = useAppStore((s) => s.clearSelectedTasks);

  const batchStatus = useBatchUpdateTaskStatus();

  const actionable = tasks.filter(
    (t) => t.status === "todo" || t.status === "in_progress",
  );
  const allActionableSelected =
    actionable.length > 0 && actionable.every((t) => selectedTaskIds.has(t.id));

  const statusCounts = {
    todo: tasks.filter((t) => t.status === "todo").length,
    in_progress: tasks.filter((t) => t.status === "in_progress").length,
    done: tasks.filter((t) => t.status === "done").length,
    cancelled: tasks.filter((t) => t.status === "cancelled").length,
  };

  const chartData = Object.entries(statusCounts)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({ name: name.replace("_", " "), value }));

  const handleMarkSelectedDone = () => {
    const ids = [...selectedTaskIds];
    if (ids.length === 0) return;
    batchStatus.mutate(
      { taskIds: ids, status: "done" },
      { onSuccess: () => clearSelectedTasks() },
    );
  };

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
          to={`/todoist?project=${project.id}`}
          className="flex items-center gap-1.5 rounded-md bg-bb-accent/20 px-3 py-1.5 text-xs font-medium text-bb-accent transition hover:bg-bb-accent/30"
        >
          <Upload size={12} /> Sync
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
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <CheckSquare size={16} /> Tasks ({tasks.length})
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectMode(!selectMode)}
              className={`flex items-center gap-1.5 rounded-md border border-bb-border px-3 py-1.5 text-xs font-medium transition ${
                selectMode
                  ? "bg-bb-accent/20 text-bb-accent"
                  : "text-bb-muted hover:text-bb-text"
              }`}
            >
              <CheckCheck size={12} /> {selectMode ? "Exit select" : "Select"}
            </button>
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
        </div>

        {selectMode && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-bb-border bg-bb-card px-3 py-2 text-xs">
            <span className="font-medium text-bb-text">
              {selectedTaskIds.size} selected
            </span>
            <button
              onClick={() =>
                allActionableSelected
                  ? clearSelectedTasks()
                  : setSelectedTasks(actionable.map((t) => t.id))
              }
              className="rounded border border-bb-border px-2 py-1 text-bb-muted transition hover:text-bb-text"
            >
              {allActionableSelected ? "Clear todo+in-progress" : "Select todo+in-progress"}
            </button>
            <div className="flex-1" />
            <button
              onClick={handleMarkSelectedDone}
              disabled={selectedTaskIds.size === 0 || batchStatus.isPending}
              className="flex items-center gap-1.5 rounded-md bg-bb-success/20 px-3 py-1.5 font-medium text-bb-success transition hover:bg-bb-success/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <CheckCheck size={12} /> {batchStatus.isPending ? "Marking…" : "Mark done"}
            </button>
            <button
              onClick={clearSelectedTasks}
              className="rounded p-1 text-bb-muted transition hover:text-bb-text"
              title="Clear selection"
            >
              <X size={14} />
            </button>
          </div>
        )}

        {taskView === "kanban" ? (
          <KanbanBoard tasks={tasks} />
        ) : (
          <div className="space-y-2">
            {tasks.length === 0 ? (
              <div className="py-4 text-center text-xs text-bb-muted">No tasks</div>
            ) : (
              tasks.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
                  selected={selectedTaskIds.has(t.id)}
                  selectMode={selectMode}
                  onToggleSelect={toggleTaskSelected}
                />
              ))
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

      <div>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
          <Bookmark size={16} /> Bookmarks ({bookmarksData?.total ?? bookmarks.length})
        </h2>
        <div className="space-y-2">
          {bookmarks.length === 0 ? (
            <div className="py-4 text-center text-xs text-bb-muted">No bookmarks</div>
          ) : (
            bookmarks.map((b) => (
              <div
                key={b.id}
                className={`rounded-lg border border-bb-border bg-bb-card p-4 ${
                  b.pinned ? "ring-1 ring-bb-accent/40" : ""
                }`}
              >
                <p className="text-sm">
                  {b.pinned && (
                    <Bookmark size={12} className="mr-1 inline text-bb-accent" />
                  )}
                  {b.note_text}
                </p>
                <div className="mt-2 flex items-center gap-2 text-xs text-bb-muted">
                  <span>{b.author || "agent"}</span>
                  <span>·</span>
                  <span>{new Date(b.created_at).toLocaleString()}</span>
                  {b.tags && b.tags.length > 0 && (
                    <>
                      <span>·</span>
                      <span>{b.tags.join(", ")}</span>
                    </>
                  )}
                  <span className="flex-1" />
                  {b.transcript_id ? (
                    <Link
                      to={`/transcripts/${b.transcript_id}`}
                      className="text-bb-accent hover:underline"
                    >
                      view session
                    </Link>
                  ) : b.ingest_status === "failed" ? (
                    <span className="text-bb-muted">ingest failed</span>
                  ) : (
                    <span className="text-bb-muted">session ingesting…</span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
