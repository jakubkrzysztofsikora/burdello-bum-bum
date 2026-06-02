import { useState } from "react";
import { Link } from "react-router-dom";
import { Search, Loader2 } from "lucide-react";
import { useSearch } from "../hooks/useApi";

export function SearchPanel() {
  const [query, setQuery] = useState("");
  const [searchType, setSearchType] = useState("hybrid");
  const [searchFilters] = useState<Record<string, unknown>>({});
  const [isSearching, setIsSearching] = useState(false);

  const { data, isLoading, error } = useSearch(
    query,
    searchType,
    searchFilters,
    isSearching,
  );

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      setIsSearching(true);
    }
  };

  return (
    <div className="space-y-4">
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-bb-muted"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search transcripts, tasks, projects..."
            className="h-10 w-full rounded-lg border border-bb-border bg-bb-card pl-9 pr-3 text-sm text-bb-text placeholder:text-bb-muted focus:border-bb-accent focus:outline-none"
          />
        </div>
        <select
          value={searchType}
          onChange={(e) => setSearchType(e.target.value)}
          className="rounded-lg border border-bb-border bg-bb-card px-3 text-sm text-bb-text focus:border-bb-accent focus:outline-none"
        >
          <option value="hybrid">Hybrid</option>
          <option value="vector">Vector</option>
          <option value="fulltext">Fulltext</option>
        </select>
        <button
          type="submit"
          disabled={isLoading || !query.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-bb-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:opacity-50"
        >
          {isLoading && <Loader2 size={14} className="animate-spin" />}
          Search
        </button>
      </form>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error.message}
        </div>
      )}

      {data && (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-bb-muted">
            <span>{data.total} results</span>
          </div>
          {data.results.length === 0 ? (
            <div className="py-8 text-center text-sm text-bb-muted">
              No results found
            </div>
          ) : (
            <div className="space-y-2">
              {data.results.map((r) => (
                <Link
                  key={r.chunk_id}
                  to={`/transcripts/${r.transcript_id}`}
                  className="block rounded-lg border border-bb-border bg-bb-card p-3 transition hover:border-bb-accent/50"
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span className="text-xs text-bb-accent">
                      Open transcript →
                    </span>
                    <span className="text-xs text-bb-muted">
                      score: {r.score.toFixed(3)}
                    </span>
                  </div>
                  <p className="text-sm text-bb-text">{r.text}</p>
                  {r.metadata && Object.keys(r.metadata).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {Object.entries(r.metadata).map(([k, v]) => (
                        <span
                          key={k}
                          className="rounded bg-bb-dark px-1.5 py-0.5 text-xs text-bb-muted"
                        >
                          {k}: {String(v)}
                        </span>
                      ))}
                    </div>
                  )}
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
