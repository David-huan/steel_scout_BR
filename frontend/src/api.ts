import type { CompanyDetail, CompanyList, DedupPair, Event, Filters, Run } from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
  if (!resp.ok) {
    let message = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      message = body.detail ?? message;
    } catch {
      // keep default message
    }
    throw new Error(message);
  }
  return (await resp.json()) as T;
}

export function createRun(product: string, country: string, targetCount: number) {
  return request<{ run_id: string; status: string; brief: Run["brief"] }>("/api/runs", {
    method: "POST",
    body: JSON.stringify({ product, country, target_count: targetCount, options: {} }),
  });
}

export function getRun(runId: string) {
  return request<Run>(`/api/runs/${runId}`);
}

export function listRuns() {
  return request<{ items: Run[] }>("/api/runs?limit=20");
}

export function listCompanies(runId: string, filters: Filters) {
  const params = new URLSearchParams({ limit: "200" });
  if (filters.tier === "AB") params.set("tier", "A,B");
  else if (filters.tier) params.set("tier", filters.tier);
  if (filters.state) params.set("state", filters.state);
  if (filters.type) params.set("type", filters.type);
  if (filters.q) params.set("q", filters.q);
  if (filters.minScore) params.set("min_score", String(filters.minScore));
  if (filters.sort) params.set("sort", filters.sort);
  return request<CompanyList>(`/api/runs/${runId}/companies?${params.toString()}`);
}

export function getCompany(companyId: string) {
  return request<CompanyDetail>(`/api/companies/${companyId}`);
}

export function reviewCompany(companyId: string, status: string, note?: string) {
  return request<{ company_id: string; review_status: string; status: string }>(
    `/api/companies/${companyId}/review`,
    { method: "POST", body: JSON.stringify({ status, note: note ?? null }) },
  );
}

export function getRunEvents(runId: string) {
  return request<{ items: Event[] }>(`/api/runs/${runId}/events?limit=100`);
}

export function listDedupQueue() {
  return request<{ items: DedupPair[]; total: number }>("/api/dedup/queue");
}

export function mergePair(pairId: string, keepId: string, note?: string) {
  return request<{ pair_id: string; status: string; keep_id: string; lost_id: string }>(
    `/api/dedup/${pairId}/merge`,
    { method: "POST", body: JSON.stringify({ keep_id: keepId, note: note ?? null }) },
  );
}

export function dismissPair(pairId: string, note?: string) {
  return request<{ pair_id: string; status: string }>(`/api/dedup/${pairId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });
}

export function exportUrl(runId?: string, tier?: string, state?: string) {
  const params = new URLSearchParams();
  if (runId) params.set("run_id", runId);
  if (tier) params.set("tier", tier);
  if (state) params.set("state", state);
  return `/api/export?${params.toString()}`;
}
