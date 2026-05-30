import { useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { api } from "../services/api";

const ALL = ["chatgpt", "gemini", "perplexity", "google_ai", "google_ai_mode"];
const LABELS = {
  chatgpt: "ChatGPT",
  gemini: "Gemini",
  perplexity: "Perplexity",
  google_ai: "Google AI Overview",
  google_ai_mode: "Google AI Mode",
};

export function CaptureButton({ projectId, onStarted, initialProviders }) {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState(
    initialProviders && initialProviders.length ? initialProviders : ALL
  );
  const [forceRefresh, setForceRefresh] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const toggle = (p) =>
    setProviders((cur) =>
      cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]
    );

  const run = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.triggerCapture(projectId, {
        providers,
        force_refresh: forceRefresh,
      });
      setMsg(
        `Started: ${r.providers.length} providers × ${r.prompts} prompts` +
          (r.geo_location ? ` · ${r.geo_location}` : "")
      );
      onStarted?.();
      setOpen(false);
    } catch (e) {
      setMsg(`Failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex items-center gap-2">
      <button className="btn-outline" onClick={() => setOpen((o) => !o)}>
        {providers.length} providers
      </button>
      <button className="btn-primary" onClick={run} disabled={busy || !providers.length}>
        {busy ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
        Run capture
      </button>
      {msg && <span className="text-xs text-text-muted ml-2">{msg}</span>}
      {open && (
        <div className="absolute top-12 right-0 z-20 card p-3 flex flex-col gap-2 min-w-[220px]">
          {ALL.map((p) => (
            <label key={p} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={providers.includes(p)}
                onChange={() => toggle(p)}
              />
              {LABELS[p] || p}
            </label>
          ))}
          <div className="border-t border-border my-1" />
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={forceRefresh}
              onChange={(e) => setForceRefresh(e.target.checked)}
            />
            Force refresh (bypass cache)
          </label>
        </div>
      )}
    </div>
  );
}

export function ReprocessButton({ projectId, onDone }) {
  const [busy, setBusy] = useState(false);
  const click = async () => {
    setBusy(true);
    try {
      await api.reprocess(projectId);
      onDone?.();
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="btn-ghost" onClick={click} disabled={busy}>
      <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
      Reprocess
    </button>
  );
}
