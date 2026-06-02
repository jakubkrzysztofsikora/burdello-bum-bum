import { useState } from "react";
import { Upload, Loader2, CheckCircle } from "lucide-react";
import { useProjects } from "../hooks/useApi";
import { api } from "../api/client";
import type { Project } from "../api/types";

export function ExportPanel() {
  const { data: projectsData } = useProjects();
  const [selectedProject, setSelectedProject] = useState("");
  const [todoistProject, setTodoistProject] = useState("");
  const [isExporting, setIsExporting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  const projects: Project[] = projectsData?.items || [];

  const handleExport = async () => {
    if (!selectedProject) return;
    setIsExporting(true);
    setResult(null);
    try {
      const res = await api.exportToTodoist(selectedProject, todoistProject || undefined);
      setResult({ success: true, message: `Exported successfully! ${JSON.stringify(res)}` });
    } catch (err) {
      setResult({
        success: false,
        message: err instanceof Error ? err.message : "Export failed",
      });
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="max-w-xl space-y-4">
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-sm font-medium text-bb-muted">BB Project</label>
          <select
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
            className="w-full rounded-lg border border-bb-border bg-bb-card px-3 py-2 text-sm text-bb-text focus:border-bb-accent focus:outline-none"
          >
            <option value="">Select a project...</option>
            {projects.map((p: Project) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-bb-muted">
            Todoist Project ID (optional)
          </label>
          <input
            type="text"
            value={todoistProject}
            onChange={(e) => setTodoistProject(e.target.value)}
            placeholder="Leave empty to create new"
            className="w-full rounded-lg border border-bb-border bg-bb-card px-3 py-2 text-sm text-bb-text placeholder:text-bb-muted focus:border-bb-accent focus:outline-none"
          />
        </div>

        {selectedProject && (
          <div className="rounded-lg border border-bb-border bg-bb-dark p-3 text-xs text-bb-muted">
            <p className="mb-1 font-medium text-bb-text">Preview</p>
            <p>
              Will export all tasks from project{" "}
              <span className="text-bb-accent">
                {projects.find((p: Project) => p.id === selectedProject)?.name}
              </span>{" "}
              to Todoist.
            </p>
          </div>
        )}

        <button
          onClick={handleExport}
          disabled={isExporting || !selectedProject}
          className="flex items-center gap-2 rounded-lg bg-bb-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:opacity-50"
        >
          {isExporting ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          Export to Todoist
        </button>
      </div>

      {result && (
        <div
          className={`rounded-lg border p-3 text-sm ${
            result.success
              ? "border-green-500/30 bg-green-500/10 text-green-400"
              : "border-red-500/30 bg-red-500/10 text-red-400"
          }`}
        >
          <div className="flex items-center gap-2">
            {result.success && <CheckCircle size={14} />}
            {result.message}
          </div>
        </div>
      )}
    </div>
  );
}
