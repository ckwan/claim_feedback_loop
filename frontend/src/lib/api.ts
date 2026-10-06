/**
 * Thin fetch wrapper around the FastAPI backend. Mirrors the endpoints in
 * app/routers/*.py exactly — nothing here invents an API shape the backend
 * doesn't actually have.
 */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type ClaimStatus = "open" | "under_review" | "approved" | "denied";

export interface Claim {
  id: string;
  org_id: string;
  claimant_name: string;
  amount: number;
  status: ClaimStatus;
  history_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface Suggestion {
  id: string;
  claim_id: string;
  suggested_action: string;
  rationale: string | null;
  confidence: number;
  model_version: string;
  created_at: string;
}

export interface Feedback {
  id: string;
  suggestion_id: string;
  adjuster_id: string;
  action_taken: "accepted" | "overridden";
  final_action: string;
  override_reason: string | null;
  created_at: string;
}

export interface Adjuster {
  id: string;
  org_id: string;
  name: string;
  email: string;
}

async function request<T>(
  orgId: string,
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Org-Id": orgId,
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  createOrganization: (name: string) =>
    fetch(`${BASE_URL}/organizations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then((r) => r.json()),

  createAdjuster: (orgId: string, name: string, email: string) =>
    request<Adjuster>(orgId, "/adjusters", {
      method: "POST",
      body: JSON.stringify({ org_id: orgId, name, email }),
    }),

  listClaims: (orgId: string, status?: ClaimStatus) =>
    request<Claim[]>(
      orgId,
      `/claims${status ? `?status=${status}` : ""}`
    ),

  createClaim: (
    orgId: string,
    payload: { claimant_name: string; amount: number; history_notes?: string }
  ) =>
    request<Claim>(orgId, "/claims", {
      method: "POST",
      body: JSON.stringify({ org_id: orgId, ...payload }),
    }),

  getClaim: (orgId: string, claimId: string) =>
    request<Claim>(orgId, `/claims/${claimId}`),

  requestSuggestion: (orgId: string, claimId: string) =>
    request<Suggestion>(orgId, `/claims/${claimId}/suggest`, { method: "POST" }),

  submitFeedback: (
    orgId: string,
    suggestionId: string,
    payload: {
      adjuster_id: string;
      action_taken: "accepted" | "overridden";
      final_action: string;
      override_reason?: string;
    }
  ) =>
    request<Feedback>(orgId, `/suggestions/${suggestionId}/feedback`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getHistorySummary: (orgId: string, claimId: string) =>
    request<{ claim_id: string; summary: string }>(
      orgId,
      `/claims/${claimId}/history-summary`
    ),

  getOverrideRate: (orgId: string) =>
    request<{ total: number; overridden: number; override_rate: number }>(
      orgId,
      "/feedback/override-rate"
    ),
};
