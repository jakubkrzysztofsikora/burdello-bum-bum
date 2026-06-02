import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  MessageSquare,
  Gem,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useState } from "react";
import { format } from "date-fns";
import { StatusBadge } from "../components/StatusBadge";
import { ProviderIcon } from "../components/ProviderIcon";
import { useTranscript, useMiningResults } from "../hooks/useApi";

export function TranscriptDetail() {
  const { id } = useParams<{ id: string }>();
  const [expandedTools, setExpandedTools] = useState<Set<number>>(new Set());
  const { data: transcript, isLoading } = useTranscript(id || "");
  const { data: miningResults } = useMiningResults(id || "");

  const toggleTool = (idx: number) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  if (isLoading || !transcript) {
    return (
      <div className="space-y-4">
        <div className="h-6 w-48 animate-pulse rounded bg-slate-700" />
        <div className="h-96 animate-pulse rounded-lg bg-bb-card" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link
          to="/transcripts"
          className="rounded p-1 text-bb-muted hover:bg-bb-border hover:text-bb-text"
        >
          <ArrowLeft size={18} />
        </Link>
        <ProviderIcon provider={transcript.provider} />
        <div className="flex-1 min-w-0">
          <h1 className="truncate text-xl font-bold">
            {transcript.title || transcript.project_name || "Untitled Session"}
          </h1>
          <div className="flex items-center gap-3 text-xs text-bb-muted">
            <span>{transcript.id}</span>
            <StatusBadge status={transcript.status} />
            {transcript.model && (
              <span className="font-mono">{transcript.model}</span>
            )}
          </div>
        </div>
        {transcript.has_mining_results && (
          <span className="flex items-center gap-1 rounded-md bg-bb-warning/20 px-2 py-1 text-xs text-bb-warning">
            <Gem size={12} /> Mining Results
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <MessageSquare size={14} /> Messages (
              {transcript.messages?.length || 0})
            </h2>
            {transcript.started_at && (
              <span className="text-xs text-bb-muted">
                {format(new Date(transcript.started_at), "PPp")}
              </span>
            )}
          </div>

          <div className="space-y-2 max-h-[calc(100vh-240px)] overflow-auto pr-1">
            {!transcript.messages || transcript.messages.length === 0 ? (
              <div className="rounded-lg border border-bb-border bg-bb-card p-6 text-center text-sm text-bb-muted">
                No messages available
              </div>
            ) : (
              transcript.messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`rounded-lg border p-3 ${
                    msg.role === "user"
                      ? "border-blue-500/20 bg-blue-500/5"
                      : msg.role === "assistant"
                        ? "border-green-500/20 bg-green-500/5"
                        : "border-bb-border bg-bb-card"
                  }`}
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span
                      className={`text-xs font-semibold ${
                        msg.role === "user"
                          ? "text-blue-400"
                          : msg.role === "assistant"
                            ? "text-green-400"
                            : "text-bb-muted"
                      }`}
                    >
                      {msg.role}
                    </span>
                    {msg.timestamp && (
                      <span className="text-xs text-bb-muted">
                        {format(new Date(msg.timestamp), "HH:mm:ss")}
                      </span>
                    )}
                  </div>
                  <div className="whitespace-pre-wrap text-sm text-bb-text">
                    {msg.content}
                  </div>

                  {msg.tool_calls && msg.tool_calls.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {msg.tool_calls.map((tool, tidx) => {
                        const globalIdx = idx * 100 + tidx;
                        const isExpanded = expandedTools.has(globalIdx);
                        return (
                          <div
                            key={tidx}
                            className="rounded border border-bb-border bg-bb-dark"
                          >
                            <button
                              onClick={() => toggleTool(globalIdx)}
                              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs"
                            >
                              {isExpanded ? (
                                <ChevronDown size={10} />
                              ) : (
                                <ChevronRight size={10} />
                              )}
                              <span className="font-mono text-bb-accent">
                                {tool.name}
                              </span>
                              <span className="text-bb-muted">({tool.id})</span>
                            </button>
                            {isExpanded && (
                              <div className="border-t border-bb-border px-2 py-1.5">
                                <pre className="overflow-auto text-xs text-bb-muted">
                                  {JSON.stringify(tool.arguments, null, 2)}
                                </pre>
                                {tool.result !== undefined && (
                                  <div className="mt-1 border-t border-bb-border pt-1">
                                    <span className="text-xs text-bb-success">
                                      Result:
                                    </span>
                                    <pre className="overflow-auto text-xs text-bb-muted">
                                      {JSON.stringify(tool.result, null, 2)}
                                    </pre>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="space-y-4">
          {miningResults && miningResults.length > 0 && (
            <div className="rounded-lg border border-bb-border bg-bb-card p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <Gem size={14} /> Mining Results
              </h3>
              <div className="space-y-2">
                {miningResults.map((mr) => (
                  <div key={mr.id} className="rounded bg-bb-dark p-2">
                    <span className="text-xs font-medium text-bb-accent">
                      {mr.result_type}
                    </span>
                    <pre className="mt-1 overflow-auto text-xs text-bb-muted">
                      {JSON.stringify(mr.content, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}

          {transcript.artifacts && transcript.artifacts.length > 0 && (
            <div className="rounded-lg border border-bb-border bg-bb-card p-4">
              <h3 className="mb-2 text-sm font-semibold">Artifacts</h3>
              <div className="space-y-2">
                {transcript.artifacts.map((a) => (
                  <div key={a.id} className="rounded bg-bb-dark p-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium">{a.name}</span>
                      <span className="text-xs text-bb-muted">{a.type}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
