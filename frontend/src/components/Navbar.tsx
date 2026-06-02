import { Search, RefreshCw, Menu, Database, FileText, FolderKanban, CheckSquare } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAppStore } from "../stores/useAppStore";
import { useTriggerIngest, useStats } from "../hooks/useApi";

export function Navbar() {
  const navigate = useNavigate();
  const { toggleSidebar, lastQuery, setLastQuery } = useAppStore();
  const ingest = useTriggerIngest();
  const { data: stats } = useStats();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (lastQuery.trim()) {
      navigate(`/search?q=${encodeURIComponent(lastQuery.trim())}`);
    }
  };

  return (
    <header className="sticky top-0 z-30 flex items-center justify-between border-b border-bb-border bg-bb-card/80 px-4 py-2 backdrop-blur">
      <div className="flex items-center gap-3">
        <button
          onClick={toggleSidebar}
          className="rounded p-1.5 text-bb-muted hover:bg-bb-border hover:text-bb-text lg:hidden"
        >
          <Menu size={18} />
        </button>
        <form onSubmit={handleSearch} className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-bb-muted" />
          <input
            type="text"
            placeholder="Quick search..."
            value={lastQuery}
            onChange={(e) => setLastQuery(e.target.value)}
            className="h-8 w-48 rounded-md border border-bb-border bg-bb-dark pl-8 pr-3 text-sm text-bb-text placeholder:text-bb-muted focus:border-bb-accent focus:outline-none md:w-72"
          />
        </form>
      </div>

      <div className="flex items-center gap-4">
        {stats && (
          <div className="hidden items-center gap-3 text-xs text-bb-muted md:flex">
            <span className="flex items-center gap-1"><Database size={12} /> {stats.total_sources}</span>
            <span className="flex items-center gap-1"><FileText size={12} /> {stats.total_transcripts}</span>
            <span className="flex items-center gap-1"><FolderKanban size={12} /> {stats.total_projects}</span>
            <span className="flex items-center gap-1"><CheckSquare size={12} /> {stats.total_tasks}</span>
          </div>
        )}
        <button
          onClick={() => ingest.mutate()}
          disabled={ingest.isPending}
          className="flex items-center gap-1.5 rounded-md bg-bb-accent/20 px-3 py-1.5 text-xs font-medium text-bb-accent transition hover:bg-bb-accent/30 disabled:opacity-50"
        >
          <RefreshCw size={12} className={ingest.isPending ? "animate-spin" : ""} />
          Ingest
        </button>
      </div>
    </header>
  );
}
