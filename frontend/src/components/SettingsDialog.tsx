import { useEffect, useState } from "react";
import { api, KIND_LABEL, type Engine, type Kind, type Project, type Settings, type WorkflowInfo } from "../api";

const gb = (n?: number) => (n ? `${(n / 2 ** 30).toFixed(1)} GB` : "?");

export function SettingsDialog({
  project,
  onClose,
  onSaved,
  onDeleteProject,
}: {
  project: Project | null;
  onClose: () => void;
  onSaved: () => void;
  onDeleteProject: () => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [engine, setEngine] = useState<Engine | null>(null);
  const [testing, setTesting] = useState(false);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [proj, setProj] = useState<Project | null>(project);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.settings().then(setSettings);
    api.workflows().then(setWorkflows);
  }, []);

  const test = async (url?: string) => {
    setTesting(true);
    try {
      if (url !== undefined) setSettings(await api.saveSettings({ comfy_url: url }));
      setEngine(await api.engine());
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    setErr(null);
    try {
      if (settings) {
        await api.saveSettings({
          comfy_url: settings.comfy_url,
          keep_pc_clean: settings.keep_pc_clean,
          wait_for_idle: settings.wait_for_idle,
        });
      }
      if (proj) {
        await api.patchProject(proj.id, {
          name: proj.name,
          style: proj.style,
          negative: proj.negative,
          templates: proj.templates,
          image_workflow: proj.image_workflow,
        });
      }
      onSaved();
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const wf = workflows.find((w) => w.name === proj?.image_workflow);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="side-head">
          <h2>Settings</h2>
          <button className="icon-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <section>
          <h4>Engine PC (ComfyUI)</h4>
          {settings && (
            <>
              <div className="row">
                <input
                  value={settings.comfy_url}
                  onChange={(e) => setSettings({ ...settings, comfy_url: e.target.value })}
                  placeholder="http://home-pc:8188"
                />
                <button onClick={() => test(settings.comfy_url)} disabled={testing}>
                  {testing ? "Testing…" : "Save & test"}
                </button>
              </div>
              {engine && (
                <div className={`engine-box ${engine.online ? "ok" : "bad"}`}>
                  {engine.online ? (
                    <>
                      <b>Connected</b> · ComfyUI {engine.comfyui_version}
                      {engine.devices?.map((d) => (
                        <div key={d.name} className="small">
                          {d.name} — {gb(d.vram_free)} free of {gb(d.vram_total)}
                        </div>
                      ))}
                      <div className="small">
                        Queue: {engine.queue_running ?? 0} running, {engine.queue_pending ?? 0} waiting
                      </div>
                    </>
                  ) : (
                    <>
                      <b>Not reachable</b>
                      <div className="small">{engine.error}</div>
                      <div className="small">Is Tailscale on and ComfyUI started with --listen?</div>
                    </>
                  )}
                </div>
              )}
              <label className="check">
                <input
                  type="checkbox"
                  checked={settings.wait_for_idle}
                  onChange={(e) => setSettings({ ...settings, wait_for_idle: e.target.checked })}
                />
                <span>
                  Wait until the GPU is idle
                  <span className="muted small"> — hold my stills while Studio or anyone else has jobs queued</span>
                </span>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={settings.keep_pc_clean}
                  onChange={(e) => setSettings({ ...settings, keep_pc_clean: e.target.checked })}
                />
                <span>
                  Keep the PC clean
                  <span className="muted small"> — render to ComfyUI temp/ (wiped on restart); files live on this laptop</span>
                </span>
              </label>
              <div className="muted small">Assets are stored in {settings.data_dir}</div>
            </>
          )}
        </section>

        {proj && (
          <section>
            <h4>Project</h4>
            <label className="muted small">Name</label>
            <input value={proj.name} onChange={(e) => setProj({ ...proj, name: e.target.value })} />
            <label className="muted small">Look &amp; style (added to every prompt)</label>
            <textarea
              rows={3}
              value={proj.style}
              placeholder="e.g. Photoreal Chinese costume-drama still, 50mm prime, soft halation, gentle film grain"
              onChange={(e) => setProj({ ...proj, style: e.target.value })}
            />
            <label className="muted small">Negative prompt</label>
            <textarea rows={2} value={proj.negative} onChange={(e) => setProj({ ...proj, negative: e.target.value })} />
            <label className="muted small">Image workflow</label>
            <select value={proj.image_workflow} onChange={(e) => setProj({ ...proj, image_workflow: e.target.value })}>
              {workflows.map((w) => (
                <option key={w.name} value={w.name} disabled={!!w.error}>
                  {w.name}
                  {w.error ? " (invalid)" : ""}
                </option>
              ))}
            </select>
            {wf && (
              <div className="small muted">
                {wf.error ??
                  `Inputs (${wf.mapping_source}): ` +
                    Object.entries(wf.mapping ?? {})
                      .map(([role, t]) => `${role} → ${t.map(([n, k]) => `#${n}.${k}`).join(", ")}`)
                      .join(" · ")}
                {wf.missing && wf.missing.length > 0 && <div className="warn">Missing: {wf.missing.join(", ")}</div>}
              </div>
            )}
            <div className="small muted">Drop more API-format workflows into {settings?.workflow_dir}</div>
            <details>
              <summary>Prompt templates per card type</summary>
              <div className="muted small">
                Use {"{style}"}, {"{title}"} and {"{description}"}.
              </div>
              {(Object.keys(KIND_LABEL) as Kind[]).map((k) => (
                <div key={k}>
                  <label className="muted small">{KIND_LABEL[k]}</label>
                  <textarea
                    rows={4}
                    value={proj.templates[k]}
                    onChange={(e) => setProj({ ...proj, templates: { ...proj.templates, [k]: e.target.value } })}
                  />
                </div>
              ))}
            </details>
            <button className="danger subtle" onClick={onDeleteProject}>
              Delete project…
            </button>
          </section>
        )}

        {err && <div className="warn">{err}</div>}
        <div className="row end">
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={save}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
