import type {
  FilterParams,
  SearchResponse,
  QAResponse,
  Stats,
  WeeklySummary,
  SkillInfo,
  MiningResult,
  Transcript,
  TranscriptDetail,
  Project,
  Task,
  Source,
  Artifact,
  Bookmark,
  TodoistProjectSummary,
  TodoistSyncPlanResponse,
  TodoistSyncRunDetail,
  TodoistSyncRunListResponse,
  KbTreeResponse,
  KbNodeDetail,
  KbEntityListResponse,
  KbEntityDetail,
} from "./types";

const API_BASE = "api/v1";

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
    fetchJson(`${API_BASE}/sources/?${buildQuery(params)}`),

  // Transcripts
  listTranscripts: (
    params?: FilterParams,
  ): Promise<{ items: Transcript[]; total: number }> =>
    fetchJson(`${API_BASE}/transcripts/?${buildQuery(params)}`),
  getTranscript: (id: string): Promise<TranscriptDetail> =>
    fetchJson(`${API_BASE}/transcripts/${id}`),

  // Projects
  listProjects: (
    params?: FilterParams,
  ): Promise<{ items: Project[]; total: number }> =>
    fetchJson(`${API_BASE}/projects/?${buildQuery(params)}`),
  getProject: (
    id: string,
  ): Promise<Project & { tasks?: Task[]; transcripts?: Transcript[] }> =>
    fetchJson(`${API_BASE}/projects/${id}`),

  // Tasks
  listTasks: (
    params?: FilterParams,
  ): Promise<{ items: Task[]; total: number }> =>
    fetchJson(`${API_BASE}/tasks/?${buildQuery(params)}`),
  updateTaskStatus: (id: string, status: string): Promise<Task> =>
    // Backend expects `new_status` as a query string param, not a JSON body.
    fetchJson(
      `${API_BASE}/tasks/${id}/status?new_status=${encodeURIComponent(status)}`,
      { method: "PUT" },
    ),
  batchUpdateTaskStatus: (
    taskIds: string[],
    status: string,
  ): Promise<{ updated: number; task_ids: string[] }> =>
    fetchJson(`${API_BASE}/tasks/batch/status`, {
      method: "POST",
      body: JSON.stringify({ task_ids: taskIds, status }),
    }),

  // Artifacts
  listArtifacts: (
    params?: FilterParams,
  ): Promise<{ items: Artifact[]; total: number }> =>
    fetchJson(`${API_BASE}/artifacts/?${buildQuery(params)}`),
  getArtifact: (id: string): Promise<Artifact> =>
    fetchJson(`${API_BASE}/artifacts/${id}`),

  // Bookmarks
  listBookmarks: (
    params?: FilterParams,
  ): Promise<{ items: Bookmark[]; total: number }> =>
    fetchJson(`${API_BASE}/bookmarks/?${buildQuery(params)}`),

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
  qa: (question: string, topK = 6): Promise<QAResponse> =>
    fetchJson(`${API_BASE}/search/qa`, {
      method: "POST",
      body: JSON.stringify({ question, top_k: topK }),
    }),

  // Stats
  getStats: (): Promise<Stats> => fetchJson(`${API_BASE}/stats`),
  getWeeklySummary: (): Promise<WeeklySummary> =>
    fetchJson(`${API_BASE}/stats/weekly-summary`),

  // Skills
  listSkills: (): Promise<SkillInfo[]> => fetchJson(`${API_BASE}/skills`),

  // Ingest
  triggerIngest: (): Promise<{ status: string }> =>
    fetchJson(`${API_BASE}/ingest/`, { method: "POST" }),

  // Todoist
  listTodoistProjects: (): Promise<TodoistProjectSummary[]> =>
    fetchJson(`${API_BASE}/todoist/projects`),
  previewTodoistSync: (
    projectId: string,
    includeDone = false,
  ): Promise<TodoistSyncPlanResponse> =>
    fetchJson(
      `${API_BASE}/todoist/sync/project/${projectId}/plan?include_done=${includeDone}`,
      { method: "POST" },
    ),
  runTodoistSync: (
    projectId: string,
    includeDone = false,
  ): Promise<TodoistSyncRunDetail> =>
    fetchJson(
      `${API_BASE}/todoist/sync/project/${projectId}?include_done=${includeDone}`,
      { method: "POST" },
    ),
  listTodoistSyncRuns: (
    projectId: string,
  ): Promise<TodoistSyncRunListResponse> =>
    fetchJson(`${API_BASE}/todoist/sync/project/${projectId}/runs`),
  getTodoistSyncRun: (runId: string): Promise<TodoistSyncRunDetail> =>
    fetchJson(`${API_BASE}/todoist/sync/runs/${runId}`),
  exportToTodoist: (
    projectId: string,
    includeDone = false,
  ): Promise<TodoistSyncRunDetail> =>
    fetchJson(`${API_BASE}/todoist/export/project/${projectId}?include_done=${includeDone}`, {
      method: "POST",
    }),

  // Knowledge Base
  getKbTree: (): Promise<KbTreeResponse> =>
    fetchJson(`${API_BASE}/kb/tree`),
  getKbNode: (slug: string): Promise<KbNodeDetail> =>
    fetchJson(`${API_BASE}/kb/nodes/${encodeURIComponent(slug)}`),
  listKbEntities: (
    params: { entity_type?: string; limit?: number; offset?: number } = {},
  ): Promise<KbEntityListResponse> => {
    const search = new URLSearchParams();
    if (params.entity_type) search.set("entity_type", params.entity_type);
    if (params.limit !== undefined) search.set("limit", String(params.limit));
    if (params.offset !== undefined) search.set("offset", String(params.offset));
    const qs = search.toString();
    return fetchJson(`${API_BASE}/kb/entities/${qs ? `?${qs}` : ""}`);
  },
  getKbEntity: (slug: string): Promise<KbEntityDetail> =>
    fetchJson(`${API_BASE}/kb/entities/${encodeURIComponent(slug)}`),

  // Mining
  getMiningResults: (transcriptId: string): Promise<MiningResult[]> =>
    fetchJson(`${API_BASE}/mining/transcript/${transcriptId}`),
};
