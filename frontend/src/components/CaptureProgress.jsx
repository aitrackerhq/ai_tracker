import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, Loader2, Circle, XCircle, Cpu } from "lucide-react";
import { api } from "../services/api";
import { Card, SectionHeader, Badge } from "./ui";

const PROVIDER_LABEL = {
  chatgpt: "ChatGPT",
  gemini: "Gemini",
  perplexity: "Perplexity",
  google_ai: "Google AI Overview",
  google_ai_mode: "Google AI Mode",
};

const ACTIVE = new Set(["pending", "running", "captured"]);

function StatusNode({ status }) {
  if (status === "processed")
    return <CheckCircle2 size={18} className="text-accent-green" />;
  if (status === "error") return <XCircle size={18} className="text-accent-red" />;
  if (status === "running" || status === "captured")
    return <Loader2 size={18} className="text-accent animate-spin" />;
  return <Circle size={18} className="text-text-dim" />;
}

function StatusBadge({ status }) {
  const map = {
    processed: ["success", "Succeeded"],
    captured: ["info", "Processing"],
    running: ["warn", "Running"],
    pending: ["neutral", "Queued"],
    error: ["danger", "Failed"],
  };
  const [tone, label] = map[status] || ["neutral", status];
  return <Badge tone={tone}>{label}</Badge>;
}

/**
 * Live orchestrator panel. Polls the project's runs, picks the most recent
 * capture batch, and renders each (provider × prompt) job as a pipeline node.
 * Auto-polls every 2s while any node is still active; stops when all settle.
 */
export function CaptureProgress({ projectId, onSettled }) {
  const [batch, setBatch] = useState(null);
  const timer = useRef(null);
  const wasActive = useRef(false);

  const poll = async () => {
    try {
      const runs = await api.runs(projectId);
      const withBatch = runs.filter((r) => r.batch_id);
      if (!withBatch.length) {
        setBatch(null);
        return;
      }
      // latest batch = the batch whose newest run is most recent
      const latestId = withBatch.reduce((a, b) =>
        new Date(a.created_at) > new Date(b.created_at) ? a : b
      ).batch_id;
      const jobs = withBatch
        .filter((r) => r.batch_id === latestId)
        .sort((a, b) => a.provider.localeCompare(b.provider) || a.id - b.id);
      const active = jobs.some((j) => ACTIVE.has(j.status));
      setBatch({ id: latestId, jobs, active });

      if (active) {
        wasActive.current = true;
      } else if (wasActive.current) {
        wasActive.current = false;
        onSettled?.();
      }
    } catch {
      /* ignore transient errors while polling */
    }
  };

  useEffect(() => {
    poll();
    timer.current = setInterval(poll, 2000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Only show on the Overview while orchestration is actively running.
  // Once everything settles, this disappears and the Overview shows results only.
  // (Completed runs remain viewable on the Orchestration page.)
  if (!batch || !batch.jobs.length || !batch.active) return null;

  const total = batch.jobs.length;
  const done = batch.jobs.filter((j) => j.status === "processed" || j.status === "error").length;
  const pct = Math.round((done / total) * 100);

  // group by provider for a cleaner pipeline view
  const byProvider = {};
  for (const j of batch.jobs) {
    (byProvider[j.provider] ||= []).push(j);
  }

  return (
    <Card className="mb-6">
      <SectionHeader
        title={
          <span className="flex items-center gap-2">
            <Cpu size={16} className={batch.active ? "text-accent animate-pulse" : "text-text-muted"} />
            Capture Pipeline
          </span>
        }
        subtitle={batch.active ? "Agents are running…" : "Last run complete"}
        right={
          <span className="text-sm text-text-muted tabular-nums">
            {done}/{total} steps
          </span>
        }
      />

      <div className="h-1.5 w-full rounded-full bg-bg-panel overflow-hidden mb-5">
        <div
          className={clsx(
            "h-full rounded-full transition-all duration-500",
            batch.active ? "bg-accent" : "bg-accent-green"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="space-y-5">
        {Object.entries(byProvider).map(([provider, jobs]) => (
          <div key={provider}>
            <div className="text-xs uppercase tracking-wider text-text-muted mb-2">
              {PROVIDER_LABEL[provider] || provider}
            </div>
            <div className="relative pl-3">
              {/* connecting line */}
              <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border" />
              <div className="space-y-1.5">
                {jobs.map((j) => (
                  <div
                    key={j.id}
                    className="relative flex items-center gap-3 rounded-md px-2 py-2 hover:bg-bg-hover"
                  >
                    <div className="relative z-10 bg-bg-card rounded-full">
                      <StatusNode status={j.status} />
                    </div>
                    <span className="flex-1 text-sm truncate">{j.prompt}</span>
                    {j.status === "processed" && (
                      <span className="text-xs text-text-muted tabular-nums">
                        {j.mention_count} mentions · {j.citation_count} citations
                      </span>
                    )}
                    {j.status === "error" && j.error && (
                      <span className="text-xs text-accent-red truncate max-w-[240px]" title={j.error}>
                        {j.error}
                      </span>
                    )}
                    <StatusBadge status={j.status} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
