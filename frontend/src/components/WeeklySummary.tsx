import { Link } from "react-router-dom";
import { CheckCircle2, Loader2, AlertCircle, ExternalLink } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { useWeeklySummary } from "../hooks/useApi";
import type { WeeklySummaryItem } from "../api/types";

const BUCKET_CONFIG = {
  done: {
    label: "Done this week",
    icon: CheckCircle2,
    color: "text-green-400",
    border: "border-green-400/30",
    bg: "bg-green-400/10",
  },
  in_progress: {
    label: "In progress",
    icon: Loader2,
    color: "text-blue-400",
    border: "border-blue-400/30",
    bg: "bg-blue-400/10",
  },
  stale: {
    label: "Not picked up this week",
    icon: AlertCircle,
    color: "text-amber-400",
    border: "border-amber-400/30",
    bg: "bg-amber-400/10",
  },
} as const;

type BucketKey = keyof typeof BUCKET_CONFIG;

function SummaryItem({ item }: { item: WeeklySummaryItem }) {
  const href = item.kind === "artifact" ? `/artifacts/${item.id}` : `/tasks`;
  const updated = item.updated_at ? new Date(item.updated_at) : null;

  return (
    <Link
      to={href}
      className="group flex items-start gap-2 rounded border border-bb-border bg-bb-surface p-2 text-xs transition hover:border-bb-accent/50"
    >
      <span className="mt-0.5 shrink-0 text-bb-muted">
        {item.kind === "artifact" ? <ExternalLink size={12} /> : <span className="block h-3 w-3 rounded-full bg-bb-border" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-bb-text group-hover:text-bb-accent">
          {item.title}
        </p>
        <div className="mt-0.5 flex items-center gap-2 text-[10px] text-bb-muted">
          {item.project_name ? (
            <span className="truncate">{item.project_name}</span>
          ) : item.project_id ? (
            <span className="truncate">{item.project_id.slice(0, 8)}</span>
          ) : null}
          {item.status && (
            <span className="rounded bg-bb-border/50 px-1 py-0.5 capitalize">
              {item.status.replace("_", " ")}
            </span>
          )}
          {item.artifact_type && (
            <span className="rounded bg-bb-border/50 px-1 py-0.5 capitalize">
              {item.artifact_type}
            </span>
          )}
          {updated && (
            <span className="ml-auto shrink-0">
              {formatDistanceToNow(updated, { addSuffix: true })}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}

function BucketColumn({
  bucketKey,
  data,
}: {
  bucketKey: BucketKey;
  data: { count: number; items: WeeklySummaryItem[] } | undefined;
}) {
  const config = BUCKET_CONFIG[bucketKey];
  const Icon = config.icon;
  const items = data?.items || [];

  return (
    <div className={`rounded-lg border ${config.border} bg-bb-card p-4`}>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Icon size={14} className={config.color} />
          <span>{config.label}</span>
        </h2>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${config.bg} ${config.color}`}>
          {data?.count ?? 0}
        </span>
      </div>
      <div className="space-y-2">
        {items.length === 0 ? (
          <div className="py-4 text-center text-xs text-bb-muted">Nothing here</div>
        ) : (
          items.map((item) => <SummaryItem key={`${item.kind}-${item.id}`} item={item} />)
        )}
      </div>
    </div>
  );
}

export function WeeklySummary() {
  const { data, isLoading } = useWeeklySummary();

  if (isLoading) {
    return (
      <div className="rounded-lg border border-bb-border bg-bb-card p-6">
        <div className="text-center text-xs text-bb-muted">Loading weekly summary…</div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-bb-border bg-bb-card p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Last week</h2>
        {data?.since && (
          <span className="text-xs text-bb-muted">
            Since {new Date(data.since).toLocaleDateString()}
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <BucketColumn bucketKey="done" data={data?.done} />
        <BucketColumn bucketKey="in_progress" data={data?.in_progress} />
        <BucketColumn bucketKey="stale" data={data?.stale} />
      </div>
    </div>
  );
}
