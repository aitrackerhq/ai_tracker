import { useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { api } from "../services/api";

const ALL = ["chatgpt", "gemini", "google_ai"];

export function CaptureButton({ projectId, onStarted }) {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState(ALL);
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
      const r = await api.triggerCapture(projectId, { providers });
      setMsg(`Capture started: ${r.providers.length} providers × ${r.prompts} prompts`);
      onStarted?.();
    } catch (e) {
      setMsg(`Failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <button className="btn-outline" onClick={() => setOpen((o) => !o)}>
        {providers.length} providers
      </button>
      <button className="btn-primary" onClick={run} disabled={busy}>
        {busy ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
        Run capture
      </button>
      {msg && <span className="text-xs text-text-muted ml-2">{msg}</span>}
      {open && (
        <div className="absolute mt-12 z-10 card p-3 flex flex-col gap-2">
          {ALL.map((p) => (
            <label key={p} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={providers.includes(p)}
                onChange={() => toggle(p)}
              />
              {p}
            </label>
          ))}
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
