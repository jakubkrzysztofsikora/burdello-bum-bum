import { useState } from "react";
import { Link } from "react-router-dom";
import { Layers, FileCode } from "lucide-react";
import { useArtifacts } from "../hooks/useApi";

export function Artifacts() {
  const [page, setPage] = useState(1);
  const [type, setType] = useState<string>("");
  const pageSize = 24;

  const { data, isLoading } = useArtifacts({
    page,
    limit: pageSize,
    ...(type ? { artifact_type: type } : {}),
  });

  const artifacts = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers size={20} className="text-bb-accent" />
          <h1 className="text-2xl font-bold">Artifacts</h1>
          <span className="text-sm text-bb-muted">({total})</span>
        </div>
        <input
          value={type}
          onChange={(e) => {
            setType(e.target.value);
            setPage(1);
          }}
          placeholder="Filter by type (e.g. file, code)…"
          className="rounded-md border border-bb-border bg-bb-surface px-3 py-1.5 text-sm"
        />
      </div>

      {isLoading ? (
        <div className="text-bb-muted">Loading…</div>
      ) : artifacts.length === 0 ? (
        <div className="text-bb-muted">No artifacts found.</div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {artifacts.map((a) => {
            const content = (a.content || {}) as Record<string, unknown>;
            const filePath = (content.file_path as string) || "";
            const preview = (content.content_preview as string) || "";
            const language = (content.language as string) || "";
            return (
              <Link
                key={a.id}
                to={`/artifacts/${a.id}`}
                className="block rounded-lg border border-bb-border bg-bb-surface p-3 transition hover:border-bb-accent/50"
              >
                <div className="mb-1 flex items-center gap-2">
                  <FileCode size={14} className="shrink-0 text-bb-accent" />
                  <span className="truncate text-sm font-medium">{a.name}</span>
                </div>
                <div className="mb-2 flex flex-wrap gap-1.5 text-xs text-bb-muted">
                  <span className="rounded bg-bb-bg px-1.5 py-0.5">
                    {a.artifact_type}
                  </span>
                  {language && (
                    <span className="rounded bg-bb-bg px-1.5 py-0.5">
                      {language}
                    </span>
                  )}
                </div>
                {filePath && (
                  <div className="mb-1 truncate font-mono text-xs text-bb-muted">
                    {filePath}
                  </div>
                )}
                {preview && (
                  <p className="line-clamp-3 text-xs text-bb-muted">
                    {preview}
                  </p>
                )}
              </Link>
            );
          })}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-md border border-bb-border px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-bb-muted">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded-md border border-bb-border px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
