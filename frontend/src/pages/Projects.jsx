import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, ArrowRight, Trash2, Sparkles } from "lucide-react";

import { api } from "../services/api";
import { useFetch } from "../hooks/useFetch";
import {
  Badge,
  Card,
  EmptyState,
  SectionHeader,
  Skeleton,
} from "../components/ui";
import { PROVIDERS, PROVIDER_LABELS } from "../services/providers";

function NewProjectForm({ onCreated }) {
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [geo, setGeo] = useState("");
  const [prompts, setPrompts] = useState("");
  const [competitors, setCompetitors] = useState("");
  const [providers, setProviders] = useState(PROVIDERS);
  const [submitting, setSubmitting] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const toggleProvider = (p) =>
    setProviders((cur) =>
      cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p],
    );

  const promptLines = () =>
    prompts
      .split("\n")
      .map((p) => p.trim())
      .filter(Boolean);

  const generatePrompts = async () => {
    if (!domain.trim()) {
      setError("Enter a domain first to generate prompt suggestions.");
      return;
    }
    setSuggesting(true);
    setError(null);
    try {
      const r = await api.suggestPromptsAdhoc({
        domain: domain.trim(),
        competitors: competitors
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean),
        existing_prompts: promptLines(),
      });
      const merged = [...promptLines(), ...(r.suggestions || [])].slice(0, 5);
      setPrompts(merged.join("\n"));
    } catch (err) {
      setError(err.message);
    } finally {
      setSuggesting(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        domain: domain.trim(),
        prompts: promptLines().slice(0, 5),
        competitors: competitors
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean),
        geo_location: geo.trim() || null,
        providers,
      };
      const proj = await api.createProject(payload);
      onCreated?.();
      navigate(`/projects/${proj.id}/overview`);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <SectionHeader
        title="New Project"
        subtitle="Track a brand across AI surfaces."
      />
      <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="text-xs uppercase tracking-wider text-text-muted block mb-1">
            Name
          </label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Notion"
            required
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-wider text-text-muted block mb-1">
            Domain
          </label>
          <input
            className="input"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="notion.so"
            required
          />
        </div>
        <div className="md:col-span-2">
          <label className="text-xs uppercase tracking-wider text-text-muted block mb-1">
            Geo location (optional)
          </label>
          <input
            className="input"
            value={geo}
            onChange={(e) => setGeo(e.target.value)}
            placeholder="United States  ·  London, England  ·  Mumbai, India"
          />
          <p className="text-xs text-text-dim mt-1">
            Used for Google AI Overview / AI Mode location-aware results.
          </p>
        </div>
        <div className="md:col-span-2">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs uppercase tracking-wider text-text-muted">
              Prompts (one per line, max 5)
            </label>
            <button
              type="button"
              className="btn-ghost text-xs py-1"
              onClick={generatePrompts}
              disabled={suggesting}
              title="Generate prompt ideas from the domain using AI"
            >
              <Sparkles size={13} />
              {suggesting ? "Generating…" : "Generate with AI"}
            </button>
          </div>
          <textarea
            className="input min-h-[120px] font-mono"
            value={prompts}
            onChange={(e) => setPrompts(e.target.value)}
            placeholder={
              "best project management software\nbest collaboration tools\nalternatives to confluence"
            }
          />
        </div>
        <div className="md:col-span-2">
          <label className="text-xs uppercase tracking-wider text-text-muted block mb-1">
            Competitors (comma separated, optional)
          </label>
          <input
            className="input"
            value={competitors}
            onChange={(e) => setCompetitors(e.target.value)}
            placeholder="clickup, confluence"
          />
        </div>
        <div className="md:col-span-2">
          <label className="text-xs uppercase tracking-wider text-text-muted block mb-2">
            Track across
          </label>
          <div className="flex flex-wrap gap-3">
            {PROVIDERS.map((p) => (
              <label
                key={p}
                className="flex items-center gap-2 text-sm cursor-pointer rounded-md border border-border px-3 py-2 hover:bg-bg-hover"
              >
                <input
                  type="checkbox"
                  checked={providers.includes(p)}
                  onChange={() => toggleProvider(p)}
                />
                {PROVIDER_LABELS[p]}
              </label>
            ))}
          </div>
        </div>
        {error && (
          <div className="md:col-span-2 text-sm text-accent-red">{error}</div>
        )}
        <div className="md:col-span-2 flex justify-end">
          <button
            className="btn-primary"
            type="submit"
            disabled={submitting || !providers.length}
          >
            <Plus size={16} />
            {submitting ? "Creating…" : "Create project"}
          </button>
        </div>
      </form>
    </Card>
  );
}

export default function Projects() {
  const { data, loading, error, reload } = useFetch(
    () => api.listProjects(),
    [],
  );
  const [deletingIds, setDeletingIds] = useState(new Set());
  const [deleteError, setDeleteError] = useState(null);

  const remove = (id) => {
    if (!confirm("Delete this project and all its runs?")) return;

    // Optimistically hide the card immediately.
    setDeletingIds((prev) => new Set(prev).add(id));
    setDeleteError(null);

    api
      .deleteProject(id)
      .then(() => {
        // Backend confirmed — sync the canonical list.
        reload();
      })
      .catch((err) => {
        // Rollback: make the card reappear and surface the error.
        setDeletingIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        setDeleteError(`Failed to delete project: ${err.message}`);
      });
  };

  // Derive the visible list by filtering out optimistically-deleted ids.
  const visibleProjects = (data ?? []).filter((p) => !deletingIds.has(p.id));

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">Projects</h1>
        <p className="text-sm text-text-muted mt-1">
          Each project tracks a single brand across ChatGPT, Gemini, and Google
          AI Overviews.
        </p>
      </div>

      <NewProjectForm onCreated={reload} />

      <div>
        <SectionHeader title="Existing projects" />
        {deleteError && (
          <Card className="mb-4">
            <div className="text-sm text-accent-red">{deleteError}</div>
          </Card>
        )}
        {loading ? (
          <Card>
            <Skeleton className="h-6 w-1/3 mb-2" />
            <Skeleton className="h-4 w-1/2" />
          </Card>
        ) : error ? (
          <Card>
            <div className="text-sm text-accent-red">
              Failed to load: {error.message}
            </div>
          </Card>
        ) : !visibleProjects.length ? (
          <EmptyState
            title="No projects yet"
            hint="Create one above to get started."
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {visibleProjects.map((p) => (
              <Card
                key={p.id}
                className="hover:border-border-strong transition-colors"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-semibold">{p.name}</div>
                    <div className="text-xs font-mono text-text-muted mt-0.5">
                      {p.domain}
                    </div>
                  </div>
                  <button
                    onClick={() => remove(p.id)}
                    className="text-text-dim hover:text-accent-red"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge tone="info">{p.prompts.length} prompts</Badge>
                  <Badge>{p.competitors.length} competitors</Badge>
                </div>
                <Link
                  to={`/projects/${p.id}/overview`}
                  className="mt-4 inline-flex items-center gap-1 text-sm text-accent hover:underline"
                >
                  Open <ArrowRight size={14} />
                </Link>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
