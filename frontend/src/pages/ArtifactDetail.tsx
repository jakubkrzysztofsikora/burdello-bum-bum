import { useParams, Link } from "react-router-dom";
import { ArrowLeft, FileCode } from "lucide-react";
import { useArtifact } from "../hooks/useApi";

export function ArtifactDetail() {
  const { id = "" } = useParams();
  const { data: artifact, isLoading, error } = useArtifact(id);

  if (isLoading) return <div className="text-bb-muted">Loading…</div>;
  if (error || !artifact)
    return (
      <div className="text-red-400">
        {error?.message || "Artifact not found"}
      </div>
    );

  const content = (artifact.content || {}) as Record<string, unknown>;
  const filePath = (content.file_path as string) || "";
  const language = (content.language as string) || "";
  const preview = (content.content_preview as string) || "";

  return (
    <div className="space-y-4">
      <Link
        to="/artifacts"
        className="inline-flex items-center gap-1.5 text-sm text-bb-muted transition hover:text-bb-text"
      >
        <ArrowLeft size={14} /> Back to artifacts
      </Link>

      <div className="flex items-center gap-2">
        <FileCode size={20} className="shrink-0 text-bb-accent" />
        <h1 className="text-xl font-bold">{artifact.name}</h1>
      </div>

      <div className="flex flex-wrap gap-2 text-xs text-bb-muted">
        <span className="rounded bg-bb-surface px-2 py-0.5">
          {artifact.artifact_type}
        </span>
        {language && (
          <span className="rounded bg-bb-surface px-2 py-0.5">{language}</span>
        )}
        {artifact.project_id && (
          <Link
            to={`/projects/${artifact.project_id}`}
            className="rounded bg-bb-surface px-2 py-0.5 hover:text-bb-accent"
          >
            project
          </Link>
        )}
        {artifact.source_transcript_id && (
          <Link
            to={`/transcripts/${artifact.source_transcript_id}`}
            className="rounded bg-bb-surface px-2 py-0.5 hover:text-bb-accent"
          >
            source transcript →
          </Link>
        )}
      </div>

      {filePath && (
        <div className="font-mono text-xs text-bb-muted">{filePath}</div>
      )}

      <div>
        <h2 className="mb-2 text-sm font-medium text-bb-muted">Content</h2>
        {preview ? (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-bb-border bg-bb-surface p-4 text-xs text-bb-text">
            {preview}
          </pre>
        ) : (
          <div className="text-sm text-bb-muted">
            No content preview available.
          </div>
        )}
      </div>

      {artifact.metadata && Object.keys(artifact.metadata).length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-medium text-bb-muted">Metadata</h2>
          <pre className="overflow-x-auto rounded-lg border border-bb-border bg-bb-surface p-3 text-xs text-bb-muted">
            {JSON.stringify(artifact.metadata, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
