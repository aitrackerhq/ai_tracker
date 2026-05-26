import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const palette = ["#5b8def", "#3ddc97", "#ffb84d", "#ff5d6c", "#a78bfa", "#22d3ee", "#fb7185"];

export function BrandsBarChart({ brands }) {
  const data = (brands || []).slice(0, 8).map((b) => ({
    name: b.brand,
    score: b.visibility_score,
    mentions: b.mentions,
    isTarget: b.is_target,
  }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="#22222a" vertical={false} />
        <XAxis dataKey="name" stroke="#5a5a64" fontSize={11} tick={{ fill: "#8b8b95" }} />
        <YAxis stroke="#5a5a64" fontSize={11} tick={{ fill: "#8b8b95" }} />
        <Tooltip cursor={{ fill: "rgba(91,141,239,0.08)" }} />
        <Bar dataKey="score" radius={[6, 6, 0, 0]}>
          {data.map((entry, idx) => (
            <Cell key={idx} fill={entry.isTarget ? "#3ddc97" : palette[idx % palette.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ProvidersPieChart({ providers }) {
  const data = (providers || []).map((p) => ({
    name: p.provider,
    value: p.with_target,
  }));
  if (!data.length) return null;
  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={55}
          outerRadius={90}
          stroke="#0a0a0b"
          strokeWidth={2}
        >
          {data.map((_, idx) => (
            <Cell key={idx} fill={palette[idx % palette.length]} />
          ))}
        </Pie>
        <Tooltip />
        <Legend wrapperStyle={{ color: "#8b8b95", fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function ProviderMentionMatrix({ providers, brands }) {
  if (!providers || !brands || brands.length === 0) return null;
  const data = brands.map((row) => ({ ...row }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(260, brands.length * 36)}>
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
        <CartesianGrid stroke="#22222a" horizontal={false} />
        <XAxis type="number" stroke="#5a5a64" fontSize={11} tick={{ fill: "#8b8b95" }} />
        <YAxis dataKey="brand" type="category" stroke="#5a5a64" fontSize={11} tick={{ fill: "#8b8b95" }} width={120} />
        <Tooltip cursor={{ fill: "rgba(91,141,239,0.08)" }} />
        <Legend wrapperStyle={{ color: "#8b8b95", fontSize: 12 }} />
        {providers.map((p, idx) => (
          <Bar key={p} dataKey={p} stackId="a" fill={palette[idx % palette.length]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
