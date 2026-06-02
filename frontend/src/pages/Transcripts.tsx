import { useState } from "react";
import { Search, ArrowUpDown } from "lucide-react";
import { TranscriptCard } from "../components/TranscriptCard";
import { FilterBar } from "../components/FilterBar";
import { useTranscripts } from "../hooks/useApi";
import { useAppStore } from "../stores/useAppStore";

type SortField = "started_at" | "message_count";

export function Transcripts() {
  const { filters } = useAppStore();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortField>("started_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const { data, isLoading } = useTranscripts({
    ...filters,
    search: search || undefined,
    sort,
    order,
    page,
    limit: 15,
  });

  const transcripts = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / 15);

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
        <h1 className="text-2xl font-bold">Transcripts</h1>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-bb-muted" />
          <input
            type="text"
            placeholder="Search transcripts..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="h-8 w-48 rounded-md border border-bb-border bg-bb-card pl-8 pr-3 text-sm text-bb-text placeholder:text-bb-muted focus:border-bb-accent focus:outline-none"
          />
        </div>
      </div>

      <FilterBar showProvider={true} providerOptions={["claude_code", "codex", "kimi", "vibe", "agy", "aider"]} />

      <div className="flex items-center gap-2 text-xs">
        <span className="text-bb-muted">Sort:</span>
        {(["started_at", "message_count"] as SortField[]).map((f) => (
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
        <span className="ml-auto text-bb-muted">{total} total</span>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-bb-card" />
          ))}
        </div>
      ) : transcripts.length === 0 ? (
        <div className="py-12 text-center text-sm text-bb-muted">No transcripts found</div>
      ) : (
        <div className="space-y-2">
          {transcripts.map((t) => (
            <TranscriptCard key={t.id} transcript={t} />
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
