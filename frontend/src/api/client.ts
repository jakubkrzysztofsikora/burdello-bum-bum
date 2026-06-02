import type {
  FilterParams,
  SearchResponse,
  Stats,
  SkillInfo,
  MiningResult,
  Transcript,
  TranscriptDetail,
  Project,
  Task,
  Source,
  Artifact,
} from "./types";

const API_BASE = "/api/v1";

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

function buildQuery(params?: FilterParams): string {
  if (!params) return "";
  // The API paginates with skip/limit; the UI works in 1-based pages. Translate
  // page -> skip so pagination actually advances (otherwise every page sends
  // page=N, which the API ignores, returning the same first page).
  const { page, limit, ...rest } = params as FilterParams & {
    page?: number;
    limit?: number;
  };
  const normalized: Record<string, unknown> = { ...rest };
  if (limit != null) normalized.limit = limit;
  if (page != null && page > 0) {
    normalized.skip = (page - 1) * (limit ?? 0);
  }
  const qs = new URLSearchParams();
  Object.entries(normalized).forEach(([k, v]) => {
    if (v == null) return;
    if (Array.isArray(v)) {
      v.forEach((item) => qs.append(k, item as string));
    } else {
      qs.set(k, String(v));
    }
  });
  return qs.toString();
}

export const api = {
  // Sources
  listSources: (
    params?: FilterParams,
  ): Promise<{ items: Source[]; total: number }> =>
    fetchJson(`${API_BASE}/sources?${buildQuery(params)}`),

  // Transcripts
  listTranscripts: (
    params?: FilterParams,
  ): Promise<{ items: Transcript[]; total: number }> =>
    fetchJson(`${API_BASE}/transcripts?${buildQuery(params)}`),
  getTranscript: (id: string): Promise<TranscriptDetail> =>
    fetchJson(`${API_BASE}/transcripts/${id}`),

  // Projects
  listProjects: (
    params?: FilterParams,
  ): Promise<{ items: Project[]; total: number }> =>
    fetchJson(`${API_BASE}/projects?${buildQuery(params)}`),
  getProject: (
    id: string,
  ): Promise<Project & { tasks?: Task[]; transcripts?: Transcript[] }> =>
    fetchJson(`${API_BASE}/projects/${id}`),

  // Tasks
  listTasks: (
    params?: FilterParams,
  ): Promise<{ items: Task[]; total: number }> =>
    fetchJson(`${API_BASE}/tasks?${buildQuery(params)}`),
  updateTaskStatus: (id: string, status: string): Promise<Task> =>
    fetchJson(`${API_BASE}/tasks/${id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),

  // Artifacts
  listArtifacts: (
    params?: FilterParams,
  ): Promise<{ items: Artifact[]; total: number }> =>
    fetchJson(`${API_BASE}/artifacts?${buildQuery(params)}`),

  // Search
  search: (
    query: string,
    type = "hybrid",
    filters?: Record<string, unknown>,
  ): Promise<SearchResponse> =>
    fetchJson(`${API_BASE}/search`, {
      method: "POST",
      body: JSON.stringify({ query, type, filters }),
    }),
  findSimilar: (id: string): Promise<SearchResponse> =>
    fetchJson(`${API_BASE}/search/similar/${id}`),

  // Stats
  getStats: (): Promise<Stats> => fetchJson(`${API_BASE}/stats`),

  // Skills
  listSkills: (): Promise<SkillInfo[]> => fetchJson(`${API_BASE}/skills`),

  // Ingest
  triggerIngest: (): Promise<{ status: string }> =>
    fetchJson(`${API_BASE}/ingest`, { method: "POST" }),

  // Todoist
  exportToTodoist: (
    projectId: string,
    todoistProjectId?: string,
  ): Promise<unknown> =>
    fetchJson(`${API_BASE}/todoist/export/project/${projectId}`, {
      method: "POST",
      body: JSON.stringify({ todoist_project_id: todoistProjectId }),
    }),

  // Mining
  getMiningResults: (transcriptId: string): Promise<MiningResult[]> =>
    fetchJson(`${API_BASE}/mining/transcript/${transcriptId}`),
};
