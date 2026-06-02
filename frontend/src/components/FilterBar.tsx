import { X } from "lucide-react";
import { useAppStore } from "../stores/useAppStore";

interface FilterBarProps {
  showStatus?: boolean;
  showProvider?: boolean;
  showDate?: boolean;
  statusOptions?: string[];
  providerOptions?: string[];
}

export function FilterBar({
  showStatus = true,
  showProvider = true,
  showDate = true,
  statusOptions = ["active", "completed", "in_progress", "abandoned", "archived", "todo"],
  providerOptions = [],
}: FilterBarProps) {
  const { filters, setFilters, clearFilters } = useAppStore();

  const hasActiveFilters =
    filters.status.length > 0 ||
    filters.provider.length > 0 ||
    filters.dateFrom != null ||
    filters.dateTo != null;

  const toggleStatus = (s: string) => {
    setFilters({
      status: filters.status.includes(s)
        ? filters.status.filter((x) => x !== s)
        : [...filters.status, s],
    });
  };

  return (
    <div className="mb-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {showStatus && statusOptions.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {statusOptions.map((s) => (
              <button
                key={s}
                onClick={() => toggleStatus(s)}
                className={`rounded-full px-2.5 py-1 text-xs transition ${
                  filters.status.includes(s)
                    ? "bg-bb-accent/30 text-bb-accent border border-bb-accent/50"
                    : "border border-bb-border text-bb-muted hover:text-bb-text"
                }`}
              >
                {s.replace("_", " ")}
              </button>
            ))}
          </div>
        )}

        {showProvider && providerOptions.length > 0 && (
          <select
            value={filters.provider[0] || ""}
            onChange={(e) => {
              const v = e.target.value;
              setFilters({ provider: v ? [v] : [] });
            }}
            className="rounded-md border border-bb-border bg-bb-dark px-2 py-1 text-xs text-bb-text focus:border-bb-accent focus:outline-none"
          >
            <option value="">All providers</option>
            {providerOptions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        )}

        {showDate && (
          <div className="flex items-center gap-1">
            <input
              type="date"
              value={filters.dateFrom || ""}
              onChange={(e) => setFilters({ dateFrom: e.target.value || null })}
              className="rounded-md border border-bb-border bg-bb-dark px-2 py-1 text-xs text-bb-text focus:border-bb-accent focus:outline-none"
            />
            <span className="text-xs text-bb-muted">to</span>
            <input
              type="date"
              value={filters.dateTo || ""}
              onChange={(e) => setFilters({ dateTo: e.target.value || null })}
              className="rounded-md border border-bb-border bg-bb-dark px-2 py-1 text-xs text-bb-text focus:border-bb-accent focus:outline-none"
            />
          </div>
        )}

        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="ml-auto flex items-center gap-1 rounded-md border border-bb-border px-2 py-1 text-xs text-bb-muted hover:text-bb-text transition"
          >
            <X size={10} /> Clear
          </button>
        )}
      </div>
    </div>
  );
}
