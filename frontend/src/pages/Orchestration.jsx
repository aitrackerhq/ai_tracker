import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import clsx from "clsx";
import {
  CheckCircle2,
  Loader2,
  Circle,
  XCircle,
  Globe,
  Database,
  Braces,
  BarChart3,
} from "lucide-react";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import { Badge, Card, EmptyState, SectionHeader, Skeleton } from "../components/ui";
import { ProjectHeader } from "../components/ProjectHeader";

const PROVIDER_LABEL = {
  chatgpt: "ChatGPT",
  gemini: "Gemini",
  google_ai: "Google AI Overview",
};

function StageIcon({ status }) {
  if (status === "done") return <CheckCircle2 size={16} className="text-accent-green" />;
  if (status === "running") return <Loader2 size={16} className="text-accent animate-spin" />;
  if (status === "error") return <XCircle size={16} className="text-accent-red" />;
  return <Circle size={16} className="text-text-dim" />;
}

const STAGE_META = [
  { key: "capture", label: "Capture", icon: Globe },
  { key: "storage", label: "Raw Storage", icon: Database },
  { key: "ner", label: "NER Processing", icon: Braces },
  { key: "ranking", label: "Ranking & Scoring", icon: BarChart3 },
];

/** Derive the 4-stage internal flow from a run's overall status. */
function deriveStages(run) {
  const reachedRaw = !!run.raw_json_path;
  const s = run.status;
  let capture = "pending",
    storage = "pending",
    ner = "pending",
    ranking = "pending";

  if (s === "running") {
    capture = "running";
  } else if (s === "captured") {
    capture = "done";
    storage = "done";
    ner = "running";
  } else if (s === "processed") {
    capture = storage = ner = ranking = "done";
  } else if (s === "error") {
    if (reachedRaw) {
      capture = "done";
      storage = "done";
      ner = "error";
    } else {
      capture = "error";
    }
  }
  return { capture, storage, ner, ranking };
}

function overallBadge(status) {
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

function RunFlow({ run }) {
  const stages = deriveStages(run);
  return (
    <Card>
      <div className="flex items-start justify-between mb-4">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wider text-text-muted">
            {PROVIDER_LABEL[run.provider] || run.provider}
          </div>
          <div className="text-sm font-medium truncate">{run.prompt}</div>
        </div>
        {overallBadge(run.status)}
      </div>

      <div className="relative pl-3">
        <div className="absolute left-[7px] top-3 bottom-3 w-px bg-border" />
        <div className="space-y-2">
          {STAGE_META.map((stage) => {
            const st = stages[stage.key];
            const Icon = stage.icon;
            const isRanking = stage.key === "ranking";
            return (
              <div key={stage.key} className="relative flex items-center gap-3">
                <div className="relative z-10 bg-bg-card rounded-full">
                  <StageIcon status={st} />
                </div>
                <Icon size={14} className="text-text-muted shrink-0" />
                <span
                  className={clsx(
                    "text-sm flex-1",
                    st === "pending" ? "text-text-dim" : "text-text-primary"
                  )}
                >
                  {stage.label}
                </span>
                {isRanking && run.status === "processed" && (
                  <span className="text-xs text-text-muted tabular-nums">
                    {run.mention_count} mentions · {run.citation_count} citations
                  </span>
                )}
                {st === "error" && run.error && (
                  <span
                    className="text-xs text-accent-red truncate max-w-[220px]"
                    title={run.error}
                  >
                    {run.error}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

export default function Orchestration() {
  const { projectId } = useParams();
  const { data: runs, loading, reload } = useFetch(() => api.runs(projectId), [projectId]);
  const [selected, setSelected] = useState(null);

  // group runs into batches (newest first)
  const batches = useMemo(() => {
    const map = {};
    for (const r of runs || []) {
      const key = r.batch_id || "legacy";
      if (!map[key]) map[key] = { id: key, runs: [], latest: r.created_at };
      map[key].runs.push(r);
      if (new Date(r.created_at) > new Date(map[key].latest)) map[key].latest = r.created_at;
    }
    return Object.values(map).sort((a, b) => new Date(b.latest) - new Date(a.latest));
  }, [runs]);

  // auto-poll while the selected/newest batch is still active
  const activeBatch = batches.some((b) =>
    b.runs.some((r) => ["pending", "running", "captured"].includes(r.status))
  );
  useEffect(() => {
    if (!activeBatch) return;
    const t = setInterval(reload, 2000);
    return () => clearInterval(t);
  }, [activeBatch, reload]);

  useEffect(() => {
    if (!selected && batches.length) setSelected(batches[0].id);
  }, [batches, selected]);

  const current = batches.find((b) => b.id === selected) || batches[0];

  return (
    <div>
      <ProjectHeader onAction={reload} />

      {loading ? (
        <Skeleton className="h-48" />
      ) : !batches.length ? (
        <EmptyState
          title="No orchestration runs yet"
          hint="Trigger a capture from any project page to see the agent pipeline flow here."
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* batch selector */}
          <div className="lg:col-span-1">
            <SectionHeader title="Capture runs" />
            <div className="space-y-1.5">
              {batches.map((b) => {
                const done = b.runs.filter(
                  (r) => r.status === "processed" || r.status === "error"
                ).length;
                const failed = b.runs.some((r) => r.status === "error");
                const running = b.runs.some((r) =>
                  ["pending", "running", "captured"].includes(r.status)
                );
                return (
                  <button
                    key={b.id}
                    onClick={() => setSelected(b.id)}
                    className={clsx(
                      "w-full text-left rounded-md border px-3 py-2.5 transition-colors",
                      current?.id === b.id
                        ? "border-accent bg-bg-hover"
                        : "border-border hover:bg-bg-hover"
                    )}
                  >
                    <div className="text-sm font-medium">
                      {b.latest ? new Date(b.latest).toLocaleString() : b.id}
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      {running ? (
                        <Badge tone="warn">running</Badge>
                      ) : failed ? (
                        <Badge tone="danger">partial</Badge>
                      ) : (
                        <Badge tone="success">done</Badge>
                      )}
                      <span className="text-xs text-text-muted tabular-nums">
                        {done}/{b.runs.length} steps
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* selected batch flow */}
          <div className="lg:col-span-3">
            <SectionHeader
              title="Orchestration flow"
              subtitle="Per-run agent pipeline: capture → storage → NER → ranking"
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {current?.runs
                .slice()
                .sort((a, b) => a.provider.localeCompare(b.provider) || a.id - b.id)
                .map((r) => (
                  <RunFlow key={r.id} run={r} />
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
