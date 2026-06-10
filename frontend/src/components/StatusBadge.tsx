interface StatusBadgeProps {
  status: string;
  className?: string;
}

const STATUS_MAP: Record<string, { bg: string; text: string; label: string }> = {
  active: { bg: "bg-blue-500/20", text: "text-blue-400", label: "Active" },
  completed: { bg: "bg-green-500/20", text: "text-green-400", label: "Completed" },
  done: { bg: "bg-green-500/20", text: "text-green-400", label: "Done" },
  in_progress: { bg: "bg-yellow-500/20", text: "text-yellow-400", label: "In Progress" },
  abandoned: { bg: "bg-red-500/20", text: "text-red-400", label: "Abandoned" },
  cancelled: { bg: "bg-red-500/20", text: "text-red-400", label: "Cancelled" },
  todo: { bg: "bg-slate-500/20", text: "text-slate-400", label: "Todo" },
  archived: { bg: "bg-slate-600/20", text: "text-slate-500", label: "Archived" },
  processed: { bg: "bg-green-500/20", text: "text-green-400", label: "Processed" },
  pending: { bg: "bg-yellow-500/20", text: "text-yellow-400", label: "Pending" },
};

export function StatusBadge({ status, className = "" }: StatusBadgeProps) {
  const s = STATUS_MAP[status] || { bg: "bg-slate-500/20", text: "text-slate-400", label: status };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${s.bg} ${s.text} ${className}`}
    >
      {s.label}
    </span>
  );
}
