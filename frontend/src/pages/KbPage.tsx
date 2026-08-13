import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { KbNodeDetail } from "../api/types";
import {
  AlertCircle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ExternalLink,
  Tag,
  XCircle,
} from "lucide-react";
import { KbTreeView } from "../components/KbTreeView";
import type { KbTreeResponse } from "../api/types";

const OUTCOME_ICONS: Record<string, typeof CheckCircle2> = {
  worked: CheckCircle2,
  failed: XCircle,
  mixed: AlertCircle,
};

export function KbPage() {
  const { slug } = useParams<{ slug: string }>();
  const [node, setNode] = useState<KbNodeDetail | null>(null);
  const [tree, setTree] = useState<KbTreeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([api.getKbNode(slug), api.getKbTree()])
      .then(([detail, t]) => {
        if (cancelled) return;
        setNode(detail);
        setTree(t);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (loading) {
    return (
      <div className="p-6 text-sm text-bb-muted">Loading page…</div>
    );
  }
  if (error) {
    return (
      <div className="p-6">
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      </div>
    );
  }
  if (!node) return null;

  const isDraft = node.status === "draft";

  return (
    <div className="space-y-6 p-6">
      <div>
        <Link
          to="/knowledge"
          className="inline-flex items-center gap-1 text-xs text-bb-muted hover:text-bb-text"
        >
          <ArrowLeft size={12} /> Knowledge base
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <header className="space-y-2">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-bb-muted">
              <span>{node.node_type}</span>
              {isDraft && (
                <span className="flex items-center gap-1 rounded bg-yellow-500/15 px-1.5 py-0.5 text-yellow-400">
                  <AlertCircle size={10} /> draft
                </span>
              )}
              {!isDraft && node.status === "published" && (
                <span className="flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-0.5 text-green-400">
                  <CheckCircle2 size={10} /> published
                </span>
              )}
            </div>
            <h1 className="text-2xl font-bold">{node.title}</h1>
            {node.summary ? (
              <div className="prose prose-invert max-w-none whitespace-pre-line text-sm leading-relaxed text-bb-text">
                {renderMarkdownBullets(node.summary)}
              </div>
            ) : (
              <p className="text-sm italic text-bb-muted">
                No summary yet — this page is awaiting curation.
              </p>
            )}
          </header>

          {node.top_terms.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold text-bb-muted">
                Key terms
              </h2>
              <div className="flex flex-wrap gap-1.5">
                {node.top_terms.map((t) => (
                  <span
                    key={t}
                    className="inline-flex items-center gap-1 rounded bg-bb-border px-2 py-0.5 text-xs"
                  >
                    <Tag size={10} /> {t}
                  </span>
                ))}
              </div>
            </section>
          )}

          {node.children.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold text-bb-muted">
                Subpages
              </h2>
              <ul className="space-y-1">
                {node.children.map((c) => (
                  <li key={c.slug}>
                    <Link
                      to={`/knowledge/${encodeURIComponent(c.slug)}`}
                      className="flex items-center justify-between rounded-md border border-bb-border bg-bb-card px-3 py-2 text-sm hover:border-bb-accent"
                    >
                      <span className="font-medium">{c.title}</span>
                      <span className="flex items-center gap-2 text-xs text-bb-muted">
                        {c.source_evidence_count > 0 && (
                          <span>{c.source_evidence_count} atoms</span>
                        )}
                        {c.status === "draft" && (
                          <span className="rounded bg-yellow-500/15 px-1.5 py-0.5 text-yellow-400">
                            draft
                          </span>
                        )}
                        <ExternalLink size={12} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h2 className="mb-2 text-sm font-semibold text-bb-muted">
              Evidence ({node.evidence.length})
            </h2>
            {node.evidence.length === 0 ? (
              <p className="text-sm italic text-bb-muted">
                No evidence yet.
              </p>
            ) : (
              <ul className="space-y-2">
                {node.evidence.map((ev) => {
                  const OutcomeIcon =
                    OUTCOME_ICONS[ev.outcome ?? ""] ?? AlertCircle;
                  return (
                    <li
                      key={ev.id}
                      className="rounded-md border border-bb-border bg-bb-card p-3 text-sm"
                    >
                      <div className="flex items-start gap-2">
                        <OutcomeIcon
                          size={14}
                          className={
                            ev.outcome === "worked"
                              ? "mt-0.5 text-green-400"
                              : ev.outcome === "failed"
                                ? "mt-0.5 text-red-400"
                                : "mt-0.5 text-bb-muted"
                          }
                        />
                        <div className="flex-1 space-y-1">
                          <div className="flex items-center gap-2 text-xs text-bb-muted">
                            {ev.transcript_id && (
                              <Link
                                to={`/transcripts/${ev.transcript_id}`}
                                className="flex items-center gap-1 hover:text-bb-accent"
                              >
                                transcript <ExternalLink size={10} />
                              </Link>
                            )}
                            {ev.project_id && (
                              <Link
                                to={`/projects/${ev.project_id}`}
                                className="flex items-center gap-1 hover:text-bb-accent"
                              >
                                project <ExternalLink size={10} />
                              </Link>
                            )}
                            {ev.outcome && (
                              <span className="rounded bg-bb-border px-1.5 py-0.5">
                                {ev.outcome}
                              </span>
                            )}
                            <span>{ev.evidence_type.replace("_", " ")}</span>
                          </div>
                          {ev.excerpt && (
                            <p className="text-bb-text">{ev.excerpt}</p>
                          )}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>

        <aside className="space-y-4">
          {tree && (
            <div className="rounded-lg border border-bb-border bg-bb-card p-3">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-bb-muted">
                <BookOpen size={14} /> Tree
              </h2>
              <KbTreeView
                roots={tree.nodes}
                selectedSlug={node.slug}
              />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function renderMarkdownBullets(text: string): JSX.Element {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, idx) => {
        const trimmed = line.trim();
        if (!trimmed) return <br key={idx} />;
        if (trimmed.startsWith("- ")) {
          return (
            <div key={idx} className="flex gap-2">
              <span className="text-bb-muted">•</span>
              <span>{trimmed.slice(2)}</span>
            </div>
          );
        }
        return <p key={idx}>{trimmed}</p>;
      })}
    </>
  );
}