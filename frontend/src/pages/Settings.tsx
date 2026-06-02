import { useState } from "react";
import { Save, Trash2, AlertTriangle } from "lucide-react";
import { useSkills } from "../hooks/useApi";
import { useAppStore } from "../stores/useAppStore";

export function Settings() {
  const { clearFilters } = useAppStore();
  const { data: skills } = useSkills();
  const [gatewayUrl, setGatewayUrl] = useState("http://localhost:4000");
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <div className="rounded-lg border border-bb-border bg-bb-card p-4">
        <h2 className="mb-3 text-sm font-semibold">LiteLLM Gateway</h2>
        <div className="space-y-2">
          <label className="block text-xs text-bb-muted">Gateway URL</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={gatewayUrl}
              onChange={(e) => setGatewayUrl(e.target.value)}
              className="flex-1 rounded-md border border-bb-border bg-bb-dark px-3 py-2 text-sm text-bb-text focus:border-bb-accent focus:outline-none"
            />
            <button
              onClick={handleSave}
              className="flex items-center gap-1.5 rounded-md bg-bb-accent/20 px-3 py-2 text-xs font-medium text-bb-accent transition hover:bg-bb-accent/30"
            >
              <Save size={12} /> {saved ? "Saved!" : "Save"}
            </button>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-bb-border bg-bb-card p-4">
        <h2 className="mb-3 text-sm font-semibold">Skills</h2>
        {skills && skills.length > 0 ? (
          <div className="space-y-2">
            {skills.map((skill) => (
              <div
                key={skill.name}
                className="flex items-center justify-between rounded-md bg-bb-dark p-3"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{skill.display_name}</span>
                    <span className="rounded bg-bb-border px-1.5 py-0.5 text-xs text-bb-muted">
                      v{skill.version}
                    </span>
                  </div>
                  <p className="text-xs text-bb-muted">{skill.description}</p>
                </div>
                <label className="relative inline-flex cursor-pointer items-center">
                  <input
                    type="checkbox"
                    defaultChecked={skill.enabled}
                    className="peer sr-only"
                  />
                  <div className="h-5 w-9 rounded-full bg-slate-600 after:absolute after:left-0.5 after:top-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition peer-checked:bg-bb-accent peer-checked:after:translate-x-4" />
                </label>
              </div>
            ))}
          </div>
        ) : (
          <div className="py-4 text-center text-xs text-bb-muted">
            {skills ? "No skills configured" : "Loading skills..."}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-bb-border bg-bb-card p-4">
        <h2 className="mb-3 text-sm font-semibold">Chunking Settings</h2>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-bb-muted">Chunk Size</label>
            <input
              type="number"
              defaultValue={1000}
              className="mt-1 w-full rounded-md border border-bb-border bg-bb-dark px-3 py-2 text-sm text-bb-text focus:border-bb-accent focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-bb-muted">Chunk Overlap</label>
            <input
              type="number"
              defaultValue={200}
              className="mt-1 w-full rounded-md border border-bb-border bg-bb-dark px-3 py-2 text-sm text-bb-text focus:border-bb-accent focus:outline-none"
            />
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-red-400">
          <AlertTriangle size={14} /> Danger Zone
        </h2>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm">Clear all filters</p>
            <p className="text-xs text-bb-muted">Reset all active filters to defaults.</p>
          </div>
          <button
            onClick={clearFilters}
            className="flex items-center gap-1.5 rounded-md border border-red-500/30 px-3 py-1.5 text-xs text-red-400 transition hover:bg-red-500/20"
          >
            <Trash2 size={12} /> Clear
          </button>
        </div>
      </div>
    </div>
  );
}
