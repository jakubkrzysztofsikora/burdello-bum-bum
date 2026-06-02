import { useState } from "react";
import { Search, ArrowUpDown } from "lucide-react";
import { ProjectCard } from "../components/ProjectCard";
import { FilterBar } from "../components/FilterBar";
import { useProjects } from "../hooks/useApi";
import { useAppStore } from "../stores/useAppStore";

type SortField = "name" | "last_activity_at" | "task_count";

export function Projects() {
  const { filters } = useAppStore();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortField>("last_activity_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const { data, isLoading } = useProjects({
    ...filters,
    search: search || undefined,
    sort,
    order,
    page,
    limit: 12,
  });

  const projects = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / 12);

  const toggleSort = (field: SortField) => {
    if (sort === field) {
      setOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSort(field);
      setOrder("desc");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Projects</h1>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-bb-muted" />
          <input
            type="text"
            placeholder="Search projects..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="h-8 w-48 rounded-md border border-bb-border bg-bb-card pl-8 pr-3 text-sm text-bb-text placeholder:text-bb-muted focus:border-bb-accent focus:outline-none"
          />
        </div>
      </div>

      <FilterBar />

      <div className="flex items-center gap-2 text-xs">
        <span className="text-bb-muted">Sort:</span>
        {(["name", "last_activity_at", "task_count"] as SortField[]).map((f) => (
          <button
            key={f}
            onClick={() => toggleSort(f)}
            className={`flex items-center gap-1 rounded px-2 py-1 transition ${
              sort === f ? "bg-bb-accent/20 text-bb-accent" : "text-bb-muted hover:text-bb-text"
            }`}
          >
            {f.replace("_", " ")}
            {sort === f && <ArrowUpDown size={10} />}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="animate-pulse rounded-lg bg-bb-card p-4">
              <div className="mb-2 h-4 w-24 rounded bg-slate-700" />
              <div className="h-3 w-full rounded bg-slate-700" />
            </div>
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="py-12 text-center text-sm text-bb-muted">No projects found</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-md border border-bb-border px-3 py-1 text-xs text-bb-muted transition hover:text-bb-text disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-xs text-bb-muted">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded-md border border-bb-border px-3 py-1 text-xs text-bb-muted transition hover:text-bb-text disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
