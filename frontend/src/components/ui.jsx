import clsx from "clsx";

export function Card({ className, children }) {
  return <div className={clsx("card p-5", className)}>{children}</div>;
}

export function Stat({ label, value, hint, accent }) {
  return (
    <Card className="flex flex-col gap-1">
      <div className="text-xs uppercase tracking-wider text-text-muted">{label}</div>
      <div
        className={clsx(
          "text-3xl font-semibold tabular-nums",
          accent === "green" && "text-accent-green",
          accent === "red" && "text-accent-red",
          accent === "amber" && "text-accent-amber",
        )}
      >
        {value}
      </div>
      {hint ? <div className="text-xs text-text-muted">{hint}</div> : null}
    </Card>
  );
}

export function Badge({ children, tone = "neutral" }) {
  const tones = {
    neutral: "border-border text-text-muted",
    success: "border-accent-green/30 text-accent-green bg-accent-green/5",
    warn: "border-accent-amber/30 text-accent-amber bg-accent-amber/5",
    danger: "border-accent-red/30 text-accent-red bg-accent-red/5",
    info: "border-accent/30 text-accent bg-accent/5",
  };
  return <span className={clsx("badge", tones[tone])}>{children}</span>;
}

export function Skeleton({ className }) {
  return <div className={clsx("skeleton h-4 w-full", className)} />;
}

export function EmptyState({ title, hint }) {
  return (
    <Card className="flex flex-col items-center justify-center text-center py-16">
      <div className="text-text-primary font-medium">{title}</div>
      {hint ? <div className="text-sm text-text-muted mt-1 max-w-md">{hint}</div> : null}
    </Card>
  );
}

export function SectionHeader({ title, subtitle, right }) {
  return (
    <div className="flex items-end justify-between mb-4">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {subtitle ? <p className="text-sm text-text-muted">{subtitle}</p> : null}
      </div>
      {right}
    </div>
  );
}
