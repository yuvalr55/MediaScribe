// Typed API client.
// The base URL and poll interval come from Vite env vars (set in frontend/.env).
// In prod, VITE_API_BASE_URL="/api" is proxied by nginx to the backend container.

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const POLL_INTERVAL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS ?? 5000);
export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? 2048);
const API_AUTH_TOKEN = import.meta.env.VITE_API_AUTH_TOKEN ?? "";
const authHeaders = API_AUTH_TOKEN ? { "X-API-Key": API_AUTH_TOKEN } : undefined;

export type JobStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface JobAccepted {
  job_id: string;
  status: JobStatus;
  deduplicated: boolean;
}

export type JobPhase = "QUEUED" | "STARTING" | "TRANSCRIBING" | "STITCHING";

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  phase: JobPhase;
  progress: number;
  original_filename: string;
  duration_seconds: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string;
  attempts: number;
}

// Slim response from GET /jobs?active=true — only fields that change during processing.
export interface JobProgressResponse {
  job_id: string;
  status: JobStatus;
  phase: JobPhase;
  progress: number;
  started_at: string;
  updated_at: string;
  error: string | null;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface TranscriptResponse {
  job_id: string;
  language: string | null;
  duration_seconds: number | null;
  text: string;
  segments: TranscriptSegment[];
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function uploadFile(file: File): Promise<JobAccepted> {
  const form = new FormData();
  form.append("file", file);
  return parse(await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: authHeaders,
    body: form,
  }));
}

export async function getStatus(jobId: string): Promise<JobStatusResponse> {
  return parse(await fetch(`${API_BASE}/jobs/${jobId}`, { headers: authHeaders }));
}

export async function getResult(jobId: string): Promise<TranscriptResponse> {
  return parse(await fetch(`${API_BASE}/jobs/${jobId}/result`, { headers: authHeaders }));
}

export async function retryJob(jobId: string): Promise<JobAccepted> {
  return parse(await fetch(`${API_BASE}/jobs/${jobId}/retry`, {
    method: "POST",
    headers: authHeaders,
  }));
}

export async function listJobs(limit?: number): Promise<JobStatusResponse[]>;
export async function listJobs(limit: number, activeOnly: true): Promise<JobProgressResponse[]>;
export async function listJobs(limit = 50, activeOnly = false): Promise<JobStatusResponse[] | JobProgressResponse[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (activeOnly) params.set("active", "true");
  return parse(await fetch(`${API_BASE}/jobs?${params}`, { headers: authHeaders }));
}

export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    method: "DELETE",
    headers: authHeaders,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? `Delete failed (${res.status})`);
  }
}

export function audioUrl(jobId: string): string {
  const token = API_AUTH_TOKEN ? `?api_key=${encodeURIComponent(API_AUTH_TOKEN)}` : "";
  return `${API_BASE}/jobs/${jobId}/audio${token}`;
}
