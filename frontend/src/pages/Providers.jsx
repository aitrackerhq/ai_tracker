import { useParams } from "react-router-dom";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import { Badge, Card, EmptyState, SectionHeader, Skeleton, Stat } from "../components/ui";
import { ProjectHeader } from "../components/ProjectHeader";
import { ProviderMentionMatrix } from "../charts/Charts";

export default function Providers() {
  const { projectId } = useParams();
  const { data, loading, reload } = useFetch(() => api.providers(projectId), [projectId]);

  return (
    <div>
      <ProjectHeader onAction={reload} />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        {(data?.summary || []).map((p) => (
          <Stat
            key={p.provider}
            label={p.provider}
            value={`${p.target_share}%`}
            hint={`${p.with_target}/${p.runs} runs · ${p.citations} citations · ${p.errors} errors`}
            accent={p.errors > 0 ? "amber" : "green"}
          />
        ))}
      </div>

      <Card>
        <SectionHeader title="Brand × Provider mentions" subtitle="Stacked across providers" />
        {loading ? (
          <Skeleton className="h-32" />
        ) : !data?.brands?.length ? (
          <EmptyState title="Not enough data yet" />
        ) : (
          <>
            <ProviderMentionMatrix providers={data.providers} brands={data.brands} />
            <div className="mt-6 overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="table-th">Brand</th>
                    {data.providers.map((p) => <th key={p} className="table-th">{p}</th>)}
                    <th className="table-th">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {data.brands.map((b) => {
                    const total = data.providers.reduce((s, p) => s + (b[p] || 0), 0);
                    return (
                      <tr key={b.brand} className="hover:bg-bg-hover">
                        <td className="table-td font-medium">{b.brand}</td>
                        {data.providers.map((p) => (
                          <td key={p} className="table-td tabular-nums">{b[p] || 0}</td>
                        ))}
                        <td className="table-td tabular-nums font-semibold">{total}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
