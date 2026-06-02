import { Link } from "react-router-dom";
import { MessageSquare, Gem } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { StatusBadge } from "./StatusBadge";
import { ProviderIcon } from "./ProviderIcon";
import type { Transcript } from "../api/types";

interface TranscriptCardProps {
  transcript: Transcript;
}

export function TranscriptCard({ transcript }: TranscriptCardProps) {
  return (
    <Link
      to={`/transcripts/${transcript.id}`}
      className="group flex items-start gap-3 rounded-lg border border-bb-border bg-bb-card p-3 transition hover:border-bb-accent/50"
    >
      <ProviderIcon provider={transcript.provider} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className="truncate text-sm font-medium group-hover:text-bb-accent">
            {transcript.project_name || "Untitled Session"}
          </span>
          <StatusBadge status={transcript.status} />
          {transcript.has_mining_results && (
            <Gem size={12} className="text-bb-warning shrink-0" />
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-bb-muted">
          <span className="flex items-center gap-1">
            <MessageSquare size={10} />
            {transcript.message_count} messages
          </span>
          {transcript.started_at && (
            <span>
              {formatDistanceToNow(new Date(transcript.started_at), { addSuffix: true })}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
