import { useState } from "react";
import { useParams } from "react-router-dom";
import { Users, Search, Sparkles } from "lucide-react";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import { Badge, Card, SectionHeader, Skeleton } from "../components/ui";
import { ProjectHeader } from "../components/ProjectHeader";

function fmt(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function TimelineRow({ icon: Icon, title, meta, when }) {
  return (
    <div className="relative flex items-start gap-3 rounded-md px-2 py-2.5 hover:bg-bg-hover">
      <div className="relative z-10 mt-0.5 bg-bg-card rounded-full p-1 border border-border">
        <Icon size={14} className="text-accent" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{title}</div>
        {meta}
      </div>
      <div className="text-xs text-text-muted whitespace-nowrap">{fmt(when)}</div>
    </div>
  );
}

function HistoryColumn({ heading, items, emptyText, render, right }) {
  return (
    <Card>
      <SectionHeader title={heading} right={right} />
      {!items?.length ? (
        <div className="text-sm text-text-muted py-8 text-center">{emptyText}</div>
      ) : (
        <div className="relative pl-3">
          <div className="absolute left-[15px] top-2 bottom-2 w-px bg-border" />
          <div className="space-y-1">{items.map(render)}</div>
        </div>
      )}
    </Card>
  );
}

export default function History() {
  const { projectId } = useParams();
  const { data, loading, reload } = useFetch(() => api.history(projectId), [projectId]);
  const [detecting, setDetecting] = useState(false);
  const [msg, setMsg] = useState(null);

  const manual = (data?.competitors || []).filter((c) => !c.inferred);
  const autoDetected = (data?.competitors || []).filter((c) => c.inferred);

  const detect = async () => {
    setDetecting(true);
    setMsg(null);
    try {
      const r = await api.detectCompetitors(projectId);
      setMsg(`Added ${r.added.length} competitor${r.added.length === 1 ? "" : "s"}`);
      reload();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setDetecting(false);
    }
  };

  const renderCompetitor = (icon) => (c, i) =>
    <TimelineRow key={i} icon={icon} title={c.name} when={c.created_at} />;

  return (
    <div>
      <ProjectHeader onAction={reload} />

      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Competitors — split into Manual + Auto-detected blocks */}
          <div className="flex flex-col gap-6">
            <HistoryColumn
              heading={
                <span className="flex items-center gap-2">
                  Manual
                  <Badge>{manual.length}</Badge>
                </span>
              }
              icon={Users}
              items={manual}
              emptyText="No manually added competitors."
              render={renderCompetitor(Users)}
            />
            <HistoryColumn
              heading={
                <span className="flex items-center gap-2">
                  Auto-detected
                  <Badge tone="info">{autoDetected.length}</Badge>
                </span>
              }
              items={autoDetected}
              emptyText="No auto-detected competitors yet."
              render={renderCompetitor(Sparkles)}
              right={
                <div className="flex items-center gap-2">
                  {msg && <span className="text-xs text-text-muted">{msg}</span>}
                  <button className="btn-outline" onClick={detect} disabled={detecting}>
                    <Sparkles size={14} />
                    {detecting ? "Detecting…" : "Auto-detect (AI)"}
                  </button>
                </div>
              }
            />
          </div>

          <HistoryColumn
            heading="Queries added"
            items={data?.queries}
            emptyText="No queries yet."
            render={(q, i) => (
              <TimelineRow key={i} icon={Search} title={q.text} when={q.created_at} />
            )}
          />
        </div>
      )}
    </div>
  );
}
