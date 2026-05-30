import { useState } from "react";
import { Sparkles, Plus, Check } from "lucide-react";
import { api } from "../services/api";
import { Card, SectionHeader } from "./ui";

/**
 * "Prompts your brand should appear in but isn't" — Gemini-generated.
 * Lets the user select suggestions and append them to the project.
 */
export function PromptSuggestions({ projectId, onAdded }) {
  const [items, setItems] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);

  const generate = async () => {
    setLoading(true);
    setError(null);
    setItems(null);
    try {
      const r = await api.suggestPrompts(projectId);
      setItems(r.suggestions || []);
      setSelected(new Set((r.suggestions || []).map((_, i) => i)));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const toggle = (i) =>
    setSelected((cur) => {
      const next = new Set(cur);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });

  const addSelected = async () => {
    const chosen = items.filter((_, i) => selected.has(i));
    if (!chosen.length) return;
    setAdding(true);
    try {
      await api.addPrompts(projectId, chosen);
      setItems(null);
      setSelected(new Set());
      onAdded?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <Card className="mb-8">
      <SectionHeader
        title={
          <span className="flex items-center gap-2">
            <Sparkles size={16} className="text-accent" />
            Prompt suggestions
          </span>
        }
        subtitle="AI-generated prompts your brand should appear in — pick and add to tracking"
        right={
          <button className="btn-outline" onClick={generate} disabled={loading}>
            {loading ? "Generating…" : "Generate"}
          </button>
        }
      />
      {error && <div className="text-sm text-accent-red mb-2">{error}</div>}
      {items && items.length === 0 && (
        <div className="text-sm text-text-muted py-6 text-center">No suggestions returned.</div>
      )}
      {items && items.length > 0 && (
        <>
          <div className="space-y-1.5">
            {items.map((s, i) => (
              <label
                key={i}
                className="flex items-center gap-3 rounded-md px-2 py-2 hover:bg-bg-hover cursor-pointer"
              >
                <input type="checkbox" checked={selected.has(i)} onChange={() => toggle(i)} />
                <span className="text-sm">{s}</span>
              </label>
            ))}
          </div>
          <div className="flex justify-end mt-4">
            <button className="btn-primary" onClick={addSelected} disabled={adding || !selected.size}>
              {adding ? <Check size={14} /> : <Plus size={14} />}
              Add {selected.size} prompt{selected.size === 1 ? "" : "s"}
            </button>
          </div>
        </>
      )}
    </Card>
  );
}
