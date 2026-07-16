export interface Transcript {
  id: string;
  provider: string;
  project_name: string | null;
  started_at: string | null;
  message_count: number;
  status: string;
  has_mining_results: boolean;
}

export interface TranscriptMessage {
  role: string;
  content: string;
  timestamp?: string;
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
}

export interface TranscriptDetail extends Transcript {
  model?: string;
  ended_at?: string | null;
  messages: TranscriptMessage[];
  artifacts: Artifact[];
}

export interface Artifact {
  id: string;
  project_id: string | null;
  artifact_type: string;
  name: string;
  content: Record<string, unknown> | null;
  source_transcript_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: "active" | "completed" | "archived" | "abandoned";
  confidence: number;
  task_count: number;
  completed_task_count: number;
  transcript_count: number;
  last_activity_at: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: "todo" | "in_progress" | "done" | "cancelled";
  priority: "low" | "medium" | "high" | "urgent";
  confidence: number;
  due_date: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Bookmark {
  id: string;
  project_id: string | null;
  transcript_id: string | null;
  session_id: string | null;
  session_path: string | null;
  note_text: string;
  author: string | null;
  ingest_status: string;
  tags: string[] | null;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface SearchResult {
  chunk_id: string;
  transcript_id: string;
  text: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  facets?: SearchFacets;
}

export interface SearchFacets {
  status: Record<string, number>;
  provider: Record<string, number>;
  project: Record<string, number>;
}

export interface Stats {
  total_sources: number;
  total_transcripts: number;
  total_projects: number;
  total_tasks: number;
  total_artifacts: number;
  total_messages: number;
  provider_breakdown: Record<string, number>;
  status_breakdown: Record<string, number>;
}

export interface WeeklySummaryItem {
  id: string;
  kind: "task" | "artifact";
  title: string;
  project_id: string | null;
  project_name: string | null;
  status?: string;
  artifact_type?: string;
  updated_at: string | null;
}

export interface WeeklySummaryBucket {
  count: number;
  items: WeeklySummaryItem[];
}

export interface WeeklySummary {
  since: string;
  done: WeeklySummaryBucket;
  in_progress: WeeklySummaryBucket;
  stale: WeeklySummaryBucket;
}

export interface SkillInfo {
  name: string;
  version: string;
  display_name: string;
  description: string;
  supported_formats: string[];
  priority: number;
  enabled: boolean;
}

export interface MiningResult {
  id: string;
  transcript_id: string;
  result_type: string;
  content: unknown;
  created_at: string;
}

export interface TodoistProjectSummary {
  id: string;
  name: string;
}

export interface TodoistEpicMatch {
  todoist_project_id: string | null;
  todoist_project_name: string | null;
  score: number | null;
  reason: string | null;
  source: string | null;
}

export interface TodoistSyncEpic {
  epic_key: string;
  epic_name: string;
  summary: string | null;
  task_count: number;
  task_ids: string[];
  match: TodoistEpicMatch;
}

export interface TodoistSyncPlanResponse {
  project_id: string;
  project_name: string;
  include_done: boolean;
  todoist_inbox_project_id: string | null;
  todoist_projects_error: string | null;
  todoist_projects: TodoistProjectSummary[];
  epics: TodoistSyncEpic[];
  skipped_done: number;
  total_tasks: number;
  eligible_tasks: number;
}

export interface TodoistSyncTaskResult {
  task_id: string;
  action: "created" | "updated" | "recreated" | "skipped" | "failed";
  status: "ok" | "skipped" | "failed";
  todoist_task_id: string | null;
  todoist_project_id: string | null;
  todoist_project_name: string | null;
  error: string | null;
}

export interface TodoistSyncRunEpicResult {
  epic_key: string;
  epic_name: string;
  summary: string | null;
  match: TodoistEpicMatch;
  tasks: TodoistSyncTaskResult[];
}

export interface TodoistSyncRunResult {
  epics: TodoistSyncRunEpicResult[];
  counts: Record<string, number>;
  errors: string[];
}

export interface TodoistSyncRunSummary {
  id: string;
  project_id: string;
  project_name: string;
  status: string;
  include_done: boolean;
  todoist_inbox_project_id: string | null;
  created_at: string;
  updated_at: string;
  error_text: string | null;
  metrics: Record<string, number>;
}

export interface TodoistSyncRunDetail extends TodoistSyncRunSummary {
  plan_data: TodoistSyncPlanResponse | null;
  result_data: TodoistSyncRunResult | null;
}

export interface TodoistSyncRunListResponse {
  total: number;
  items: TodoistSyncRunSummary[];
}

export interface Source {
  id: string;
  provider: string;
  file_path: string;
  file_size: number;
  modified_at: string;
  processed: boolean;
}

export interface FilterParams {
  status?: string[];
  provider?: string[];
  dateFrom?: string | null;
  dateTo?: string | null;
  search?: string;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  limit?: number;
  project_id?: string;
  project_name?: string | null;
}
