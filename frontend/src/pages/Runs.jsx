import { useState } from "react";
import { useParams } from "react-router-dom";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import { Badge, Card, EmptyState, SectionHeader, Skeleton, SentimentBadge } from "../components/ui";
import { ProjectHeader } from "../components/ProjectHeader";
import { Eye, X } from "lucide-react";

function statusBadge(status) {
  if (status === "processed") return <Badge tone="success">processed</Badge>;
  if (status === "captured") return <Badge tone="info">captured</Badge>;
  if (status === "running") return <Badge tone="warn">running</Badge>;
  if (status === "pending") return <Badge>queued</Badge>;
  if (status === "purged") return <Badge>purged</Badge>;
  if (status === "error") return <Badge tone="danger">error</Badge>;
  return <Badge>{status}</Badge>;
}

function RunModal({ runId, onClose }) {
  const { data, loading } = useFetch(() => api.runDetail(runId), [runId]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="card max-w-4xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-4">
          <div>
            <div className="text-xs text-text-muted">Run #{runId}</div>
            <h2 className="text-lg font-semibold">{data?.prompt ?? "…"}</h2>
            <div className="text-sm text-text-muted mt-1">
              {data?.provider} · {data && new Date(data.created_at).toLocaleString()}
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X /></button>
        </div>

        {loading || !data ? (
          <Skeleton className="h-32" />
        ) : (
          <>
            {data.error && (
              <div className="mb-4 p-3 rounded bg-accent-red/10 border border-accent-red/30 text-sm text-accent-red">
                {data.error}
              </div>
            )}
            {(data.target_sentiment || data.target_framing) && (
              <div className="mb-4 flex items-center gap-2 flex-wrap">
                <span className="text-xs uppercase tracking-wider text-text-muted">Brand framing:</span>
                <SentimentBadge sentiment={data.target_sentiment} framing={data.target_framing} />
                {data.framing_rationale && (
                  <span className="text-xs text-text-muted">— {data.framing_rationale}</span>
                )}
              </div>
            )}
            {data.screenshot_path && (
              <div className="mb-6">
                <div className="text-xs uppercase tracking-wider text-text-muted mb-2">Screenshot</div>
                <img
                  src={api.screenshotUrl(runId)}
                  alt="response"
                  className="rounded-lg border border-border max-w-full"
                />
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <div className="text-xs uppercase tracking-wider text-text-muted mb-2">Mentions ({data.mentions.length})</div>
                <div className="space-y-1">
                  {data.mentions.map((m, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <span className="text-text-dim tabular-nums w-6">#{m.mention_position}</span>
                      <span className="font-medium">{m.normalized_entity}</span>
                      {m.is_target && <Badge tone="success">target</Badge>}
                      {m.entity_name !== m.normalized_entity && (
                        <span className="text-text-muted text-xs">(from "{m.entity_name}")</span>
                      )}
                    </div>
                  ))}
                  {data.mentions.length === 0 && <div className="text-sm text-text-muted">None extracted.</div>}
                </div>
              </div>

              <div>
                <div className="text-xs uppercase tracking-wider text-text-muted mb-2">Citations ({data.citations.length})</div>
                <div className="space-y-1">
                  {data.citations.map((c, i) => (
                    <a
                      key={i}
                      href={c.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-sm hover:bg-bg-hover rounded px-2 py-1"
                    >
                      <div className="font-medium truncate">{c.title || c.domain}</div>
                      <div className="text-xs text-text-muted truncate">{c.url}</div>
                    </a>
                  ))}
                  {data.citations.length === 0 && <div className="text-sm text-text-muted">None.</div>}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Runs() {
  const { projectId } = useParams();
  const { data, loading, reload } = useFetch(() => api.runs(projectId), [projectId]);
  const [openRunId, setOpenRunId] = useState(null);

  return (
    <div>
      <ProjectHeader onAction={reload} />

      <Card>
        <SectionHeader
          title="Prompt Runs"
          subtitle="Each row is one (provider × prompt) capture."
        />
        {loading ? (
          <Skeleton className="h-32" />
        ) : !data?.length ? (
          <EmptyState title="No runs yet" hint="Trigger a capture to see results here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-th">When</th>
                  <th className="table-th">Provider</th>
                  <th className="table-th">Prompt</th>
                  <th className="table-th">Status</th>
                  <th className="table-th">Mentions</th>
                  <th className="table-th">Citations</th>
                  <th className="table-th">Target</th>
                  <th className="table-th">Framing</th>
                  <th className="table-th"></th>
                </tr>
              </thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.id} className="hover:bg-bg-hover">
                    <td className="table-td whitespace-nowrap text-text-muted">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="table-td">
                      <div className="flex items-center gap-1.5">
                        <Badge>{r.provider}</Badge>
                        {r.cached && <Badge tone="info">cached</Badge>}
                      </div>
                    </td>
                    <td className="table-td max-w-md truncate">{r.prompt}</td>
                    <td className="table-td">{statusBadge(r.status)}</td>
                    <td className="table-td tabular-nums">{r.mention_count}</td>
                    <td className="table-td tabular-nums">{r.citation_count}</td>
                    <td className="table-td">
                      {r.has_target ? <Badge tone="success">yes</Badge> : <Badge>no</Badge>}
                    </td>
                    <td className="table-td">
                      <SentimentBadge sentiment={r.target_sentiment} framing={r.target_framing} />
                    </td>
                    <td className="table-td">
                      <button onClick={() => setOpenRunId(r.id)} className="btn-ghost">
                        <Eye size={14} /> View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {openRunId !== null && (
        <RunModal runId={openRunId} onClose={() => setOpenRunId(null)} />
      )}
    </div>
  );
}
