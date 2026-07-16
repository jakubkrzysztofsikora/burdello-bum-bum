import { FileText } from "lucide-react";
import { useWeeklySummary } from "../hooks/useApi";

export function WeeklySummary() {
  const { data, isLoading, error } = useWeeklySummary();

  if (isLoading) {
    return (
      <div className="rounded-lg border border-bb-border bg-bb-card p-6">
        <div className="text-center text-xs text-bb-muted">Generating weekly summary…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-bb-border bg-bb-card p-6">
        <div className="text-xs text-red-400">
          Failed to load summary: {error.message}
        </div>
      </div>
    );
  }

  const summary = data?.summary || "No summary available.";

  return (
    <div className="rounded-lg border border-bb-border bg-bb-card p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <FileText size={14} /> Last week
      </h2>
      <div className="space-y-3 text-sm leading-relaxed text-bb-text whitespace-pre-line">
        {summary}
      </div>
    </div>
  );
}
