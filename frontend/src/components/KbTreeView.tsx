import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ChevronRight,
  ChevronDown,
  BookOpen,
  FileText,
  Tags,
  AlertCircle,
} from "lucide-react";
import type { KbNodeSummary } from "../api/types";

interface KbTreeViewProps {
  roots: KbNodeSummary[];
  selectedSlug?: string | null;
}

const NODE_ICONS: Record<string, typeof BookOpen> = {
  category: BookOpen,
  subcategory: Tags,
  topic: FileText,
};

export function KbTreeView({ roots, selectedSlug }: KbTreeViewProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const next = new Set<string>();
    for (const root of roots) next.add(root.slug);
    return next;
  });

  const toggle = (slug: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  if (roots.length === 0) {
    return (
      <div className="rounded-lg border border-bb-border bg-bb-card p-6 text-center text-sm text-bb-muted">
        <BookOpen className="mx-auto mb-2 text-bb-muted" size={28} />
        No knowledge-base nodes yet. Run{" "}
        <code className="rounded bg-bb-border px-1.5 py-0.5 text-xs">
          kb_cluster_task
        </code>{" "}
        to populate the tree from transcript atoms.
      </div>
    );
  }

  return (
    <ul className="space-y-1">
      {roots.map((root) => (
        <KbTreeNode
          key={root.slug}
          node={root}
          depth={0}
          expanded={expanded}
          toggle={toggle}
          selectedSlug={selectedSlug ?? null}
        />
      ))}
    </ul>
  );
}

interface KbTreeNodeProps {
  node: KbNodeSummary;
  depth: number;
  expanded: Set<string>;
  toggle: (slug: string) => void;
  selectedSlug: string | null;
}

function KbTreeNode({
  node,
  depth,
  expanded,
  toggle,
  selectedSlug,
}: KbTreeNodeProps) {
  const hasChildren = node.children.length > 0;
  const isOpen = expanded.has(node.slug);
  const Icon = NODE_ICONS[node.node_type] ?? BookOpen;
  const isSelected = node.slug === selectedSlug;
  const isDraft = node.status === "draft";

  return (
    <li>
      <div
        className={`group flex items-center gap-2 rounded-md border px-2 py-1.5 text-sm transition ${
          isSelected
            ? "border-bb-accent bg-bb-accent/10"
            : "border-transparent hover:bg-bb-border/60"
        }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {hasChildren ? (
          <button
            onClick={() => toggle(node.slug)}
            className="rounded p-0.5 text-bb-muted hover:text-bb-text"
            aria-label={isOpen ? "Collapse" : "Expand"}
          >
            {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <Icon
          size={depth === 0 ? 16 : 13}
          className={
            depth === 0
              ? "text-bb-accent"
              : depth === 1
                ? "text-purple-400"
                : "text-bb-muted"
          }
        />
        <Link
          to={`/knowledge/${encodeURIComponent(node.slug)}`}
          className="flex-1 truncate font-medium hover:text-bb-accent"
        >
          {node.title}
        </Link>
        {isDraft && (
          <span
            title="Draft — pending human review"
            className="flex items-center gap-1 rounded bg-bb-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-bb-muted"
          >
            <AlertCircle size={10} /> draft
          </span>
        )}
        {node.source_evidence_count > 0 && (
          <span className="text-xs text-bb-muted">
            {node.source_evidence_count}
          </span>
        )}
      </div>
      {hasChildren && isOpen && (
        <ul className="space-y-1 pt-1">
          {node.children.map((child) => (
            <KbTreeNode
              key={child.slug}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
              selectedSlug={selectedSlug}
            />
          ))}
        </ul>
      )}
    </li>
  );
}