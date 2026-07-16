import { Link } from "react-router-dom";
import { Search, RefreshCw, Upload, TrendingUp, FileText, FolderKanban, Pin } from "lucide-react";
import { StatsCards } from "../components/StatsCards";
import { WeeklySummary } from "../components/WeeklySummary";
import { TranscriptCard } from "../components/TranscriptCard";
import { ProjectCard } from "../components/ProjectCard";
import { useStats, useTranscripts, useProjects, useTriggerIngest, useBookmarks } from "../hooks/useApi";
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

const COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#a855f7", "#ec4899", "#06b6d4"];

export function Dashboard() {
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: transcriptsData } = useTranscripts({ limit: 10, sort: "started_at", order: "desc" });
  const { data: projectsData } = useProjects({ limit: 5, sort: "last_activity_at", order: "desc" });
  const { data: bookmarksData } = useBookmarks({ limit: 10 });
  const ingest = useTriggerIngest();

  const transcripts = transcriptsData?.items || [];
  const projects = projectsData?.items || [];
  const bookmarks = bookmarksData?.items || [];

  const statusChartData = stats
    ? Object.entries(stats.status_breakdown).map(([name, value]) => ({ name, value }))
    : [];

  const providerChartData = stats
    ? Object.entries(stats.provider_breakdown).map(([name, value]) => ({ name, value }))
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <div className="flex gap-2">
          <Link
            to="/search"
            className="flex items-center gap-1.5 rounded-md border border-bb-border px-3 py-1.5 text-xs text-bb-muted transition hover:text-bb-text"
          >
            <Search size={12} /> Search
          </Link>
          <button
            onClick={() => ingest.mutate()}
            disabled={ingest.isPending}
            className="flex items-center gap-1.5 rounded-md bg-bb-accent/20 px-3 py-1.5 text-xs font-medium text-bb-accent transition hover:bg-bb-accent/30 disabled:opacity-50"
          >
            <RefreshCw size={12} className={ingest.isPending ? "animate-spin" : ""} /> Ingest
          </button>
          <Link
            to="/todoist"
            className="flex items-center gap-1.5 rounded-md border border-bb-border px-3 py-1.5 text-xs text-bb-muted transition hover:text-bb-text"
          >
            <Upload size={12} /> Sync
          </Link>
        </div>
      </div>

      <StatsCards stats={stats} isLoading={statsLoading} />

      <WeeklySummary />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
            <TrendingUp size={14} /> Status Breakdown
          </h2>
          {statusChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={statusChartData}
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  dataKey="value"
                  nameKey="name"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {statusChartData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
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
            <div className="py-8 text-center text-xs text-bb-muted">No data</div>
          )}
        </div>

        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
            <FileText size={14} /> Provider Breakdown
          </h2>
          {providerChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={providerChartData}>
                <XAxis dataKey="name" tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1e293b",
                    border: "1px solid #334155",
                    borderRadius: "6px",
                    fontSize: "12px",
                  }}
                />
                <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="py-8 text-center text-xs text-bb-muted">No data</div>
          )}
        </div>
      </div>

      {bookmarks.length > 0 && (
        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Pin size={14} /> Bookmarks
            </h2>
          </div>
          <div className="space-y-2">
            {bookmarks.map((b) => (
              <div
                key={b.id}
                className="rounded border border-bb-border bg-bb-surface p-3 text-xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-bb-text whitespace-pre-line leading-relaxed">
                    {b.note_text.length > 200
                      ? b.note_text.slice(0, 200) + "..."
                      : b.note_text}
                  </p>
                  {b.pinned && <Pin size={10} className="mt-0.5 shrink-0 text-bb-accent" />}
                </div>
                {b.tags && b.tags.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {b.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-bb-accent/10 px-1.5 py-0.5 text-[10px] text-bb-accent"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-2 flex items-center gap-2 text-[10px] text-bb-muted">
                  <span>{b.author || "unknown"}</span>
                  <span>·</span>
                  <span>{new Date(b.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <FileText size={14} /> Recent Transcripts
            </h2>
            <Link to="/transcripts" className="text-xs text-bb-accent hover:underline">
              View all
            </Link>
          </div>
          <div className="space-y-2">
            {transcripts.length === 0 ? (
              <div className="py-4 text-center text-xs text-bb-muted">No transcripts yet</div>
            ) : (
              transcripts.map((t) => <TranscriptCard key={t.id} transcript={t} />)
            )}
          </div>
        </div>

        <div className="rounded-lg border border-bb-border bg-bb-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <FolderKanban size={14} /> Recent Projects
            </h2>
            <Link to="/projects" className="text-xs text-bb-accent hover:underline">
              View all
            </Link>
          </div>
          <div className="space-y-3">
            {projects.length === 0 ? (
              <div className="py-4 text-center text-xs text-bb-muted">No projects yet</div>
            ) : (
              projects.map((p) => <ProjectCard key={p.id} project={p} />)
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
