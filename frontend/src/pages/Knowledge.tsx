import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  KbEntitySummary,
  KbTreeResponse,
} from "../api/types";
import { KbTreeView } from "../components/KbTreeView";
import { Library, Search, Tags } from "lucide-react";

type Tab = "tree" | "index";

const ENTITY_TYPES: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "tool", label: "Tools" },
  { value: "library", label: "Libraries" },
  { value: "framework", label: "Frameworks" },
  { value: "pattern", label: "Patterns" },
  { value: "technique", label: "Techniques" },
  { value: "concept", label: "Concepts" },
];

export function Knowledge() {
  const [tab, setTab] = useState<Tab>("tree");
  const [tree, setTree] = useState<KbTreeResponse | null>(null);
  const [treeLoading, setTreeLoading] = useState(true);
  const [treeError, setTreeError] = useState<string | null>(null);

  const [entities, setEntities] = useState<KbEntitySummary[]>([]);
  const [entityType, setEntityType] = useState<string>("");
  const [entitySearch, setEntitySearch] = useState("");
  const [entitiesLoading, setEntitiesLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setTreeLoading(true);
    setTreeError(null);
    api
      .getKbTree()
      .then((data) => {
        if (!cancelled) setTree(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setTreeError(err.message);
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (tab !== "index") return;
    let cancelled = false;
    setEntitiesLoading(true);
    api
      .listKbEntities({ entity_type: entityType || undefined, limit: 200 })
      .then((data) => {
        if (!cancelled) setEntities(data.entities);
      })
      .finally(() => {
        if (!cancelled) setEntitiesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, entityType]);

  const filteredEntities = entities.filter((e) =>
    entitySearch
      ? `${e.canonical_name} ${e.aliases.join(" ")}`
          .toLowerCase()
          .includes(entitySearch.toLowerCase())
      : true,
  );

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Knowledge Base</h1>
          <p className="text-sm text-bb-muted">
            Curated engineering knowledge mined from your transcripts.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-bb-border bg-bb-card p-1">
          <button
            onClick={() => setTab("tree")}
            className={`flex items-center gap-1.5 rounded px-3 py-1 text-sm transition ${
              tab === "tree"
                ? "bg-bb-accent/20 text-bb-accent"
                : "text-bb-muted hover:text-bb-text"
            }`}
          >
            <Library size={14} /> Tree
          </button>
          <button
            onClick={() => setTab("index")}
            className={`flex items-center gap-1.5 rounded px-3 py-1 text-sm transition ${
              tab === "index"
                ? "bg-bb-accent/20 text-bb-accent"
                : "text-bb-muted hover:text-bb-text"
            }`}
          >
            <Tags size={14} /> Index
          </button>
        </div>
      </div>

      {tab === "tree" && (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <div className="rounded-lg border border-bb-border bg-bb-card p-4">
            <h2 className="mb-3 text-sm font-semibold text-bb-muted">
              Tree
            </h2>
            {treeLoading && (
              <div className="py-8 text-center text-sm text-bb-muted">
                Loading tree…
              </div>
            )}
            {treeError && (
              <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                {treeError}
              </div>
            )}
            {tree && (
              <>
                <KbTreeView roots={tree.nodes} />
                <p className="mt-4 border-t border-bb-border pt-3 text-xs text-bb-muted">
                  {tree.total_nodes} nodes · {tree.total_published} published
                </p>
              </>
            )}
          </div>
          <div className="rounded-lg border border-bb-border bg-bb-card p-4 text-sm">
            <h2 className="mb-3 text-sm font-semibold text-bb-muted">
              About
            </h2>
            <p className="text-bb-muted">
              Each leaf summarises a recurring engineering pattern, tool, or
              technique observed across your transcripts. Pages link back to
              the projects and transcripts that contributed evidence.
            </p>
            <p className="mt-3 text-bb-muted">
              Draft nodes (badge shown) have a single source and are pending
              human review. Pages with two or more corroborating transcripts
              auto-publish.
            </p>
          </div>
        </div>
      )}

      {tab === "index" && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search
                size={14}
                className="absolute left-2 top-1/2 -translate-y-1/2 text-bb-muted"
              />
              <input
                value={entitySearch}
                onChange={(e) => setEntitySearch(e.target.value)}
                placeholder="Filter by name or alias…"
                className="w-full rounded-md border border-bb-border bg-bb-card py-1.5 pl-7 pr-3 text-sm focus:border-bb-accent focus:outline-none"
              />
            </div>
            <select
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              className="rounded-md border border-bb-border bg-bb-card px-3 py-1.5 text-sm"
            >
              {ENTITY_TYPES.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="rounded-lg border border-bb-border bg-bb-card">
            {entitiesLoading ? (
              <div className="p-8 text-center text-sm text-bb-muted">
                Loading…
              </div>
            ) : filteredEntities.length === 0 ? (
              <div className="p-8 text-center text-sm text-bb-muted">
                No entities yet. Run the entity extraction pass to populate
                the index.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-bb-border text-left text-xs uppercase tracking-wide text-bb-muted">
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium">Mentions</th>
                    <th className="px-4 py-2 font-medium">Aliases</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEntities.map((e) => (
                    <tr
                      key={e.id}
                      className="border-b border-bb-border/50 last:border-b-0 hover:bg-bb-border/30"
                    >
                      <td className="px-4 py-2">
                        <Link
                          to={`/knowledge/entity/${encodeURIComponent(e.canonical_name)}`}
                          className="font-medium text-bb-text hover:text-bb-accent"
                        >
                          {e.canonical_name}
                        </Link>
                      </td>
                      <td className="px-4 py-2">
                        <span className="rounded bg-bb-border px-1.5 py-0.5 text-xs">
                          {e.entity_type}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-bb-muted">
                        {e.mention_count}
                      </td>
                      <td className="px-4 py-2 text-xs text-bb-muted">
                        {e.aliases.slice(0, 4).join(", ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}