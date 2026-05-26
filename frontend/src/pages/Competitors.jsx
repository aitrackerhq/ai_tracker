import { useParams } from "react-router-dom";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import { Badge, Card, EmptyState, SectionHeader, Skeleton } from "../components/ui";
import { ProjectHeader } from "../components/ProjectHeader";

export default function Competitors() {
  const { projectId } = useParams();
  const { data, loading, reload } = useFetch(() => api.competitors(projectId), [projectId]);

  return (
    <div>
      <ProjectHeader onAction={reload} />
      <Card>
        <SectionHeader
          title="Competitors"
          subtitle={data?.target ? `Brands co-mentioned with ${data.target}` : "Run a capture first"}
        />
        {loading ? (
          <Skeleton className="h-32" />
        ) : !data?.competitors?.length ? (
          <EmptyState title="No competitors detected yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-th">Brand</th>
                  <th className="table-th">Co-mentions w/ target</th>
                  <th className="table-th">Mentions</th>
                  <th className="table-th">Avg pos.</th>
                  <th className="table-th">Providers</th>
                  <th className="table-th">Visibility</th>
                </tr>
              </thead>
              <tbody>
                {data.competitors.map((c) => (
                  <tr key={c.brand} className="hover:bg-bg-hover">
                    <td className="table-td font-medium">{c.brand}</td>
                    <td className="table-td tabular-nums">{c.co_mention_with_target}</td>
                    <td className="table-td tabular-nums">{c.mentions}</td>
                    <td className="table-td tabular-nums">{c.avg_position ?? "—"}</td>
                    <td className="table-td">
                      <div className="flex gap-1 flex-wrap">
                        {c.providers.map((p) => <Badge key={p}>{p}</Badge>)}
                      </div>
                    </td>
                    <td className="table-td tabular-nums">{c.visibility_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
