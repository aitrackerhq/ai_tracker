const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
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
  supportedProviders: () => request("/api/providers"),
  screenshotUrl: (rid) => `${BASE}/api/artifacts/screenshot/${rid}`,
};
