import { supabase } from "../lib/supabase";

const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, opts = {}) {
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const token = session?.access_token;

  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
    ...opts,
  });

  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${txt}`);
  }

  if (res.status === 204) return null;

  return res.json();
}

export const api = {
  listProjects: () => request("/api/projects"),
  getProject: (id) => request(`/api/projects/${id}`),
  createProject: (payload) =>
    request("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  deleteProject: (id) => request(`/api/projects/${id}`, { method: "DELETE" }),
  triggerCapture: (id, payload) =>
    request(`/api/projects/${id}/capture`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reprocess: (id) =>
    request(`/api/projects/${id}/reprocess`, { method: "POST" }),
  overview: (id) => request(`/api/projects/${id}/overview`),
  runs: (id) => request(`/api/projects/${id}/runs`),
  runDetail: (rid) => request(`/api/runs/${rid}`),
  competitors: (id) => request(`/api/projects/${id}/competitors`),
  providers: (id) => request(`/api/projects/${id}/providers`),
  timeseries: (id) => request(`/api/projects/${id}/timeseries`),
  history: (id) => request(`/api/projects/${id}/history`),
  framingContext: (id) => request(`/api/projects/${id}/framing-context`),
  llmStatus: () => request(`/api/llm/status`),
  suggestPrompts: (id) =>
    request(`/api/projects/${id}/suggest-prompts`, { method: "POST" }),
  suggestPromptsAdhoc: (body) =>
    request(`/api/llm/suggest-prompts`, { method: "POST", body: JSON.stringify(body) }),
  addPrompts: (id, prompts) =>
    request(`/api/projects/${id}/prompts`, {
      method: "POST",
      body: JSON.stringify({ prompts }),
    }),
  detectCompetitors: (id) =>
    request(`/api/projects/${id}/detect-competitors`, { method: "POST" }),
  supportedProviders: () => request("/api/providers"),
  screenshotUrl: (rid) => `${BASE}/api/artifacts/screenshot/${rid}`,
};
