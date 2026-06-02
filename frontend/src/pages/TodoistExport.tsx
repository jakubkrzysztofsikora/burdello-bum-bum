import { Upload, History } from "lucide-react";
import { ExportPanel } from "../components/ExportPanel";

export function TodoistExport() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Todoist Export</h1>
        <p className="text-sm text-bb-muted">
          Export tasks from Burdello Bum-Bum projects to your Todoist account.
        </p>
      </div>

      <div className="rounded-lg border border-bb-border bg-bb-card p-4">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
          <Upload size={14} /> New Export
        </h2>
        <ExportPanel />
      </div>

      <div className="rounded-lg border border-bb-border bg-bb-card p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <History size={14} /> Export History
        </h2>
        <div className="py-6 text-center text-xs text-bb-muted">
          Export history will appear here.
        </div>
      </div>
    </div>
  );
}
