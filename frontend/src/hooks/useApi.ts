import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FilterParams, Stats, Transcript, TranscriptDetail, Project, Task, SearchResponse, SkillInfo, MiningResult } from "../api/types";

const STALE_TIME = 30_000;

// Stats
export function useStats() {
  return useQuery<Stats, Error>({
    queryKey: ["stats"],
    queryFn: () => api.getStats(),
    staleTime: STALE_TIME,
  });
}

// Transcripts
export function useTranscripts(params?: FilterParams) {
  return useQuery<{ items: Transcript[]; total: number }, Error>({
    queryKey: ["transcripts", params],
    queryFn: () => api.listTranscripts(params),
    staleTime: STALE_TIME,
  });
}

export function useTranscript(id: string) {
  return useQuery<TranscriptDetail, Error>({
    queryKey: ["transcript", id],
    queryFn: () => api.getTranscript(id),
    enabled: !!id,
    staleTime: STALE_TIME,
  });
}

// Projects
export function useProjects(params?: FilterParams) {
  return useQuery<{ items: Project[]; total: number }, Error>({
    queryKey: ["projects", params],
    queryFn: () => api.listProjects(params),
    staleTime: STALE_TIME,
  });
}

export function useProject(id: string) {
  return useQuery<Project & { tasks?: Task[]; transcripts?: Transcript[] }, Error>({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id),
    enabled: !!id,
    staleTime: STALE_TIME,
  });
}

// Tasks
export function useTasks(params?: FilterParams) {
  return useQuery<{ items: Task[]; total: number }, Error>({
    queryKey: ["tasks", params],
    queryFn: () => api.listTasks(params),
    staleTime: STALE_TIME,
  });
}

export function useUpdateTaskStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.updateTaskStatus(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

// Search
export function useSearch(query: string, type = "hybrid", filters?: Record<string, unknown>, enabled = false) {
  return useQuery<SearchResponse, Error>({
    queryKey: ["search", query, type, filters],
    queryFn: () => api.search(query, type, filters),
    enabled: enabled && query.length > 0,
    staleTime: STALE_TIME,
  });
}

// Skills
export function useSkills() {
  return useQuery<SkillInfo[], Error>({
    queryKey: ["skills"],
    queryFn: () => api.listSkills(),
    staleTime: STALE_TIME,
  });
}

// Mining
export function useMiningResults(transcriptId: string) {
  return useQuery<MiningResult[], Error>({
    queryKey: ["mining", transcriptId],
    queryFn: () => api.getMiningResults(transcriptId),
    enabled: !!transcriptId,
    staleTime: STALE_TIME,
  });
}

// Ingest
export function useTriggerIngest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.triggerIngest(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["transcripts"] });
      qc.invalidateQueries({ queryKey: ["sources"] });
    },
  });
}
