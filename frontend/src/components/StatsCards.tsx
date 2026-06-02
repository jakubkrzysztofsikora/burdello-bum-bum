import { FileText, FolderKanban, CheckSquare, MessageSquare, Database, Layers } from "lucide-react";
import type { Stats } from "../api/types";

interface StatsCardsProps {
  stats: Stats | undefined;
  isLoading: boolean;
}

const CARDS = [
  { key: "total_sources" as const, label: "Sources", icon: Database, color: "text-cyan-400" },
  { key: "total_transcripts" as const, label: "Transcripts", icon: FileText, color: "text-blue-400" },
  { key: "total_projects" as const, label: "Projects", icon: FolderKanban, color: "text-purple-400" },
  { key: "total_tasks" as const, label: "Tasks", icon: CheckSquare, color: "text-green-400" },
  { key: "total_artifacts" as const, label: "Artifacts", icon: Layers, color: "text-orange-400" },
  { key: "total_messages" as const, label: "Messages", icon: MessageSquare, color: "text-pink-400" },
];

export function StatsCards({ stats, isLoading }: StatsCardsProps) {
  if (isLoading || !stats) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {CARDS.map((c) => (
          <div key={c.key} className="animate-pulse rounded-lg bg-bb-card p-4">
            <div className="mb-2 h-4 w-16 rounded bg-slate-700" />
            <div className="h-8 w-12 rounded bg-slate-700" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
      {CARDS.map((c) => {
        const Icon = c.icon;
        const value = stats[c.key];
        return (
          <div
            key={c.key}
            className="rounded-lg border border-bb-border bg-bb-card p-4 transition hover:border-bb-accent/50"
          >
            <div className="mb-1 flex items-center gap-2">
              <Icon size={16} className={c.color} />
              <span className="text-xs text-bb-muted">{c.label}</span>
            </div>
            <div className="text-2xl font-bold">
              {typeof value === "number" ? value.toLocaleString() : "0"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
