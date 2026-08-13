import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { KbEntityDetail } from "../api/types";
import {
  ArrowLeft,
  ExternalLink,
  Hash,
  Tag,
  XCircle,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

const OUTCOME_STYLES: Record<string, string> = {
  worked: "text-green-400",
  failed: "text-red-400",
  mixed: "text-yellow-400",
};

const OUTCOME_ICONS: Record<string, typeof CheckCircle2> = {
  worked: CheckCircle2,
  failed: XCircle,
  mixed: AlertCircle,
};

export function KbEntity() {
  const { slug } = useParams<{ slug: string }>();
  const [entity, setEntity] = useState<KbEntityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getKbEntity(slug)
      .then((data) => {
        if (!cancelled) setEntity(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
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
      <div className="p-6 text-sm text-bb-muted">Loading entity…</div>
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
  if (!entity) return null;

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

      <header className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="rounded bg-bb-accent/20 px-2 py-0.5 text-xs uppercase tracking-wide text-bb-accent">
            {entity.entity_type}
          </span>
          <h1 className="text-2xl font-bold">{entity.canonical_name}</h1>
        </div>

        {entity.description && (
          <p className="text-sm text-bb-text">{entity.description}</p>
        )}

        <div className="flex flex-wrap gap-3 text-xs text-bb-muted">
          <span className="flex items-center gap-1">
            <Hash size={12} /> {entity.mention_count} mention
            {entity.mention_count === 1 ? "" : "s"}
          </span>
          {entity.aliases.length > 0 && (
            <span className="flex items-center gap-1">
              <Tag size={12} /> {entity.aliases.join(", ")}
            </span>
          )}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        {entity.how_used && (
          <section className="rounded-lg border border-bb-border bg-bb-card p-4">
            <h2 className="mb-2 text-sm font-semibold text-bb-muted">
              How used
            </h2>
            <p className="whitespace-pre-line text-sm">{entity.how_used}</p>
          </section>
        )}
        {entity.why_used && (
          <section className="rounded-lg border border-bb-border bg-bb-card p-4">
            <h2 className="mb-2 text-sm font-semibold text-bb-muted">
              Why used
            </h2>
            <p className="whitespace-pre-line text-sm">{entity.why_used}</p>
          </section>
        )}
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-bb-muted">
          Mentions ({entity.mentions.length})
        </h2>
        {entity.mentions.length === 0 ? (
          <p className="text-sm italic text-bb-muted">
            No mentions recorded yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {entity.mentions.map((m) => {
              const OutcomeIcon =
                OUTCOME_ICONS[m.outcome ?? ""] ?? AlertCircle;
              return (
                <li
                  key={m.id}
                  className="rounded-md border border-bb-border bg-bb-card p-3 text-sm"
                >
                  <div className="flex items-start gap-2">
                    <OutcomeIcon
                      size={14}
                      className={`mt-0.5 ${OUTCOME_STYLES[m.outcome ?? ""] ?? "text-bb-muted"}`}
                    />
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2 text-xs text-bb-muted">
                        {m.transcript_id && (
                          <Link
                            to={`/transcripts/${m.transcript_id}`}
                            className="flex items-center gap-1 hover:text-bb-accent"
                          >
                            transcript <ExternalLink size={10} />
                          </Link>
                        )}
                        {m.project_id && (
                          <Link
                            to={`/projects/${m.project_id}`}
                            className="flex items-center gap-1 hover:text-bb-accent"
                          >
                            project <ExternalLink size={10} />
                          </Link>
                        )}
                        {m.first_seen_at && (
                          <span>
                            first seen{" "}
                            {new Date(m.first_seen_at).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                      {m.context_excerpt && (
                        <p className="text-bb-text">{m.context_excerpt}</p>
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
  );
}