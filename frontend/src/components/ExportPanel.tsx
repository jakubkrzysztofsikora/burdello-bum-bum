import { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { ArrowRight, Loader2, RefreshCw, CheckCircle, CircleAlert } from "lucide-react";
import { useProjects, useTodoistSyncPlan, useTodoistSyncRuns, useRunTodoistSync } from "../hooks/useApi";
import type { Project } from "../api/types";

export function ExportPanel() {
  const [searchParams] = useSearchParams();
  const initialProject = searchParams.get("project") || "";
  const [selectedProject, setSelectedProject] = useState(initialProject);
  const [includeDone, setIncludeDone] = useState(false);

  const { data: projectsData } = useProjects();
  const projects: Project[] = projectsData?.items || [];
  const planQuery = useTodoistSyncPlan(selectedProject, includeDone);
  const runsQuery = useTodoistSyncRuns(selectedProject);
  const runMutation = useRunTodoistSync();

  useEffect(() => {
    if (!selectedProject && initialProject) {
      setSelectedProject(initialProject);
    }
  }, [initialProject, selectedProject]);

  const handleRun = async () => {
    if (!selectedProject) return;
    await runMutation.mutateAsync({ projectId: selectedProject, includeDone });
  };

  const preview = planQuery.data;
  const history = runsQuery.data?.items || [];

  return (
    <div className="max-w-4xl space-y-5">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto]">
        <div>
          <label className="mb-1 block text-sm font-medium text-bb-muted">Burdello Project</label>
          <select
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
            className="w-full rounded-lg border border-bb-border bg-bb-card px-3 py-2 text-sm text-bb-text focus:border-bb-accent focus:outline-none"
          >
            <option value="">Select a project...</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-end gap-2 rounded-lg border border-bb-border bg-bb-card px-3 py-2 text-sm text-bb-muted">
          <input
            type="checkbox"
            checked={includeDone}
            onChange={(e) => setIncludeDone(e.target.checked)}
            className="h-4 w-4 rounded border-bb-border bg-bb-dark text-bb-accent focus:ring-bb-accent"
          />
          Include done tasks
        </label>

        <button
          onClick={handleRun}
          disabled={!selectedProject || runMutation.isPending}
          className="flex items-center justify-center gap-2 rounded-lg bg-bb-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:opacity-50"
        >
          {runMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Run Sync
        </button>
      </div>

      {selectedProject && (
        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold">Sync Preview</h2>
              <p className="text-xs text-bb-muted">
                The pipeline groups tasks into epics, matches them to existing Todoist projects, and falls back to Inbox when needed.
              </p>
            </div>
            <button
              onClick={() => planQuery.refetch()}
              className="flex items-center gap-1.5 rounded-md border border-bb-border px-3 py-1.5 text-xs text-bb-muted transition hover:text-bb-text"
            >
              <RefreshCw size={12} /> Refresh
            </button>
          </div>

          {planQuery.isLoading ? (
            <div className="py-6 text-center text-xs text-bb-muted">Building preview…</div>
          ) : planQuery.error ? (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
              {planQuery.error.message}
            </div>
          ) : preview ? (
            <div className="space-y-4">
              {preview.todoist_projects_error && (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                  Todoist project lookup failed for preview. The epic plan is still available, but project matching may fall back to Inbox.
                </div>
              )}
              <div className="grid gap-3 md:grid-cols-4">
                <Stat label="Tasks" value={preview.eligible_tasks} />
                <Stat label="Epics" value={preview.epics.length} />
                <Stat label="Inbox" value={preview.todoist_inbox_project_id ? "yes" : "no"} />
                <Stat label="Skipped" value={preview.skipped_done} />
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-md border border-bb-border bg-bb-dark p-3">
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-bb-muted">
                    Epic Routing
                  </h3>
                  <div className="space-y-2">
                    {preview.epics.map((epic) => (
                      <div key={epic.epic_key} className="rounded-md border border-bb-border bg-bb-card p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium">{epic.epic_name}</p>
                            <p className="text-xs text-bb-muted">
                              {epic.summary || "No summary"} · {epic.task_count} tasks
                            </p>
                          </div>
                          <div className="text-right text-xs text-bb-muted">
                            <p>{epic.match.todoist_project_name || "Inbox"}</p>
                            <p>{epic.match.source}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                    {preview.epics.length === 0 && (
                      <div className="py-4 text-center text-xs text-bb-muted">No tasks to sync</div>
                    )}
                  </div>
                </div>

                <div className="rounded-md border border-bb-border bg-bb-dark p-3">
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-bb-muted">
                    Todoist Projects
                  </h3>
                  <div className="space-y-2">
                    {preview.todoist_projects.map((project) => (
                      <div
                        key={project.id}
                        className="flex items-center justify-between rounded-md border border-bb-border bg-bb-card px-3 py-2 text-sm"
                      >
                        <span>{project.name}</span>
                        <span className="text-xs text-bb-muted">{project.id}</span>
                      </div>
                    ))}
                    {preview.todoist_projects.length === 0 && (
                      <div className="py-4 text-center text-xs text-bb-muted">No Todoist projects found</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-bb-muted">Select a project to preview the sync.</div>
          )}
        </div>
      )}

      {runMutation.data && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 p-4 text-sm text-green-300">
          <div className="mb-2 flex items-center gap-2">
            <CheckCircle size={14} />
            Sync run {runMutation.data.status}
          </div>
          <p className="text-xs text-green-200/80">
            {runMutation.data.project_name} · {runMutation.data.result_data?.counts?.created || 0} created,{" "}
            {runMutation.data.result_data?.counts?.updated || 0} updated,{" "}
            {runMutation.data.result_data?.counts?.skipped || 0} skipped
          </p>
        </div>
      )}

      {history.length > 0 && (
        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <CircleAlert size={14} /> Recent Runs
          </h2>
          <div className="space-y-2">
            {history.map((run) => (
              <div
                key={run.id}
                className="flex items-center justify-between rounded-md border border-bb-border bg-bb-dark px-3 py-2 text-sm"
              >
                <div>
                  <p className="font-medium">{run.project_name}</p>
                  <p className="text-xs text-bb-muted">
                    {new Date(run.created_at).toLocaleString()} · {run.status}
                  </p>
                </div>
                <Link
                  to={`/todoist?project=${run.project_id}`}
                  className="flex items-center gap-1 text-xs text-bb-accent hover:underline"
                >
                  reopen <ArrowRight size={12} />
                </Link>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-bb-border bg-bb-dark p-3">
      <p className="text-xs uppercase tracking-wide text-bb-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}
