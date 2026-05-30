import { X } from "lucide-react";
import { Badge } from "./ui";
import { PROVIDER_LABELS } from "../services/providers";

/**
 * Shows the runs that contributed to a clicked sentiment/framing pill, with the
 * rationale and a raw response excerpt (the actual evidence).
 *
 * filter: { type: "sentiment" | "framing", value: string }
 * items: framing-context items from the API
 */
export function FramingContextModal({ filter, items, onClose }) {
  if (!filter) return null;
  const matching = (items || []).filter((it) => it[filter.type] === filter.value);

  const tone =
    filter.value === "positive" || filter.value === "leader"
      ? "success"
      : filter.value === "negative" || filter.value === "cautionary"
      ? "danger"
      : "neutral";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="card max-w-3xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-xs uppercase tracking-wider text-text-muted">
              {filter.type === "sentiment" ? "Sentiment" : "Framing"} context
            </div>
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Badge tone={tone}>{filter.value}</Badge>
              <span className="text-text-muted text-sm font-normal">
                {matching.length} run{matching.length === 1 ? "" : "s"}
              </span>
            </h2>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary">
            <X />
          </button>
        </div>

        {matching.length === 0 ? (
          <div className="text-sm text-text-muted py-8 text-center">No runs for this value.</div>
        ) : (
          <div className="space-y-4">
            {matching.map((it) => (
              <div key={it.run_id} className="rounded-lg border border-border p-3">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <Badge>{PROVIDER_LABELS[it.provider] || it.provider}</Badge>
                  {it.sentiment && it.sentiment !== "not-mentioned" && (
                    <Badge
                      tone={
                        it.sentiment === "positive"
                          ? "success"
                          : it.sentiment === "negative"
                          ? "danger"
                          : "neutral"
                      }
                    >
                      {it.sentiment}
                    </Badge>
                  )}
                  {it.framing && it.framing !== "not-mentioned" && (
                    <Badge
                      tone={
                        it.framing === "leader"
                          ? "success"
                          : it.framing === "cautionary"
                          ? "danger"
                          : "neutral"
                      }
                    >
                      {it.framing}
                    </Badge>
                  )}
                </div>
                <div className="text-sm font-medium">{it.prompt}</div>
                {it.rationale && (
                  <div className="text-sm text-text-muted mt-1 italic">“{it.rationale}”</div>
                )}
                {it.excerpt && (
                  <div className="mt-2 text-xs text-text-muted bg-bg-panel border border-border rounded p-2 max-h-40 overflow-y-auto whitespace-pre-wrap">
                    {it.excerpt}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
