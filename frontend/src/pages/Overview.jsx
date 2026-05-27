import { useParams } from "react-router-dom";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import { Card, EmptyState, SectionHeader, Skeleton, Stat, Badge } from "../components/ui";
import { ProjectHeader } from "../components/ProjectHeader";
import { CaptureProgress } from "../components/CaptureProgress";
import { BrandsBarChart, ProvidersPieChart, VisibilityTrendChart } from "../charts/Charts";

export default function Overview() {
  const { projectId } = useParams();
  const { data, loading, reload } = useFetch(() => api.overview(projectId), [projectId]);
  const { data: trend } = useFetch(() => api.timeseries(projectId), [projectId]);

  if (loading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-10 w-1/3" />
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}
        </div>
      </div>
    );
  }

  if (!data) return <EmptyState title="Project not found" />;

  return (
    <div>
      <ProjectHeader onAction={reload} />

      <CaptureProgress projectId={projectId} onSettled={reload} />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Stat
          label="Visibility Score"
          value={`${data.visibility_score?.toFixed?.(1) ?? 0}`}
          hint={data.target_brand ? `target: ${data.target_brand}` : "no target detected yet"}
          accent="green"
        />
        <Stat label="Total Mentions" value={data.total_mentions} />
        <Stat label="Citations" value={data.total_citations} />
        <Stat
          label="Prompts × Providers"
          value={`${data.total_prompts} × ${data.providers.length}`}
          hint={`${data.total_runs} total runs`}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <Card className="lg:col-span-2">
          <SectionHeader title="Top brands by visibility" subtitle="Higher = more pervasive across your prompts" />
          {data.top_brands?.length ? (
            <BrandsBarChart brands={data.top_brands} />
          ) : (
            <div className="text-sm text-text-muted py-12 text-center">
              No mentions captured yet. Click "Run capture" to start.
            </div>
          )}
        </Card>
        <Card>
          <SectionHeader title="Target appearance by provider" />
          {data.providers?.some((p) => p.with_target > 0) ? (
            <ProvidersPieChart providers={data.providers} />
          ) : (
            <div className="text-sm text-text-muted py-12 text-center">No target appearances yet.</div>
          )}
        </Card>
      </div>

      <Card className="mb-8">
        <SectionHeader
          title="Visibility trend"
          subtitle="Competitor AI visibility vs. your AI agent mentions over time"
        />
        {trend?.points?.length ? (
          <VisibilityTrendChart points={trend.points} />
        ) : (
          <div className="text-sm text-text-muted py-12 text-center">
            Trend appears once you have captures across multiple days.
          </div>
        )}
      </Card>

      <Card>
        <SectionHeader title="Top brands" />
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="table-th">Brand</th>
                <th className="table-th">Mentions</th>
                <th className="table-th">Prompts</th>
                <th className="table-th">Providers</th>
                <th className="table-th">Avg pos.</th>
                <th className="table-th">Citations</th>
                <th className="table-th">Visibility</th>
              </tr>
            </thead>
            <tbody>
              {data.top_brands.map((b) => (
                <tr key={b.brand} className="hover:bg-bg-hover">
                  <td className="table-td">
                    <span className="font-medium">{b.brand}</span>
                    {b.is_target && <Badge tone="success" >target</Badge>}
                  </td>
                  <td className="table-td tabular-nums">{b.mentions}</td>
                  <td className="table-td tabular-nums">{b.prompts_appeared_in}</td>
                  <td className="table-td">
                    <div className="flex gap-1 flex-wrap">
                      {b.providers.map((p) => <Badge key={p}>{p}</Badge>)}
                    </div>
                  </td>
                  <td className="table-td tabular-nums">{b.avg_position ?? "—"}</td>
                  <td className="table-td tabular-nums">{b.citations}</td>
                  <td className="table-td tabular-nums font-semibold">{b.visibility_score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
