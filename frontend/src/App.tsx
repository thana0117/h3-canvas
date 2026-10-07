import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  type Node,
} from "@xyflow/react";
import { api, KIND_LABEL, thumbUrl, type Engine, type Kind, type Project } from "./api";
import { BoardContext, useBoard, useBoardPolling } from "./board";
import { CardNode } from "./components/CardNode";
import { Lightbox } from "./components/Lightbox";
import { SettingsDialog } from "./components/SettingsDialog";

const nodeTypes = { card: CardNode };
const CARD_W = 300;
const CARD_H = 560;
const GAP = 32;
const LAST_PROJECT = "h3canvas.project";

function readLast() {
  try {
    return localStorage.getItem(LAST_PROJECT);
  } catch {
    return null;
  }
}

function EnginePill({ engine, busy, onClick }: { engine: Engine | null; busy: number; onClick: () => void }) {
  let cls = "pill unknown";
  let text = "Engine…";
  if (engine) {
    if (!engine.online) {
      cls = "pill bad";
      text = "PC offline";
    } else if (busy > 0) {
      cls = "pill busy";
      text = `GPU busy · ${busy} queued`;
    } else {
      cls = "pill ok";
      text = engine.devices?.[0]?.name?.replace(/^cuda:\d+\s*/, "").split(":")[0] ?? "PC online";
    }
  }
  return (
    <button className={cls} onClick={onClick} title={engine?.error ?? engine?.url}>
      <span className="dot" />
      {text}
    </button>
  );
}

function Canvas({ projectId, onAdd }: { projectId: string; onAdd: (fn: (kind: Kind) => void) => void }) {
  const ctx = useBoardPolling(projectId);
  const { board, refresh } = ctx;
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const flow = useReactFlow();

  // Mirror cards into React Flow nodes, keeping local positions (drags) authoritative.
  useEffect(() => {
    if (!board) return;
    setNodes((prev) => {
      const pos = new Map(prev.map((n) => [n.id, n.position]));
      const sel = new Set(prev.filter((n) => n.selected).map((n) => n.id));
      return board.cards.map((c) => ({
        id: c.id,
        type: "card",
        position: pos.get(c.id) ?? { x: c.x, y: c.y },
        selected: sel.has(c.id),
        data: { cardId: c.id },
        dragHandle: ".card-head",
      }));
    });
  }, [board?.cards, setNodes]);

  const addCard = useCallback(
    async (kind: Kind) => {
      const center = flow.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
      // Step right from the viewport centre until the spot doesn't overlap another card.
      const placed = flow.getNodes().map((n) => ({ x: n.position.x, y: n.position.y, w: n.measured?.width ?? CARD_W, h: n.measured?.height ?? CARD_H }));
      let x = center.x - CARD_W / 2;
      const y = center.y - CARD_H / 2;
      while (placed.some((r) => x < r.x + r.w + GAP && x + CARD_W + GAP > r.x && y < r.y + r.h && y + CARD_H > r.y)) {
        x += CARD_W + GAP;
      }
      await api.createCard(projectId, { kind, x: Math.round(x), y: Math.round(y) });
      await refresh();
    },
    [flow, projectId, refresh],
  );

  useEffect(() => onAdd(addCard), [addCard, onAdd]);

  return (
    <BoardWrapper ctx={ctx}>
      <ReactFlow
        nodes={nodes}
        edges={[]}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, node) => api.patchCard(node.id, { x: node.position.x, y: node.position.y })}
        minZoom={0.15}
        maxZoom={2}
        fitView
        fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        deleteKeyCode={null}
        colorMode="dark"
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#2a2a33" />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={(n) => kindColor(board?.cards.find((c) => c.id === n.id)?.kind)} maskColor="rgba(10,10,14,0.7)" />
      </ReactFlow>
      {board && board.cards.length === 0 && (
        <div className="empty-hint">
          <h2>Start your scope material</h2>
          <p>Add a character, a scene or a prop. Each card generates stills with Qwen Image on your PC and keeps every variant here on the laptop.</p>
          <div className="row center">
            {(["character", "scene", "prop"] as Kind[]).map((k) => (
              <button key={k} className={`add-btn kind-${k}`} onClick={() => addCard(k)}>
                + {KIND_LABEL[k]}
              </button>
            ))}
          </div>
        </div>
      )}
    </BoardWrapper>
  );
}

function kindColor(kind?: Kind) {
  return kind === "character" ? "#a78bfa" : kind === "scene" ? "#2dd4bf" : kind === "prop" ? "#fbbf24" : "#555";
}

// Provides the board context + lightbox + library + toasts around the canvas.
function BoardWrapper({ ctx, children }: { ctx: ReturnType<typeof useBoardPolling>; children: React.ReactNode }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const toast = useCallback((m: string) => {
    setToastMsg(m);
    window.setTimeout(() => setToastMsg((cur) => (cur === m ? null : cur)), 3500);
  }, []);
  const value = useMemo(
    () => ({ board: ctx.board, refresh: ctx.refresh, openAsset: setOpenId, toast }),
    [ctx.board, ctx.refresh, toast],
  );
  return (
    <BoardContext.Provider value={value}>
      {children}
      <LibraryPanel />
      {openId && <Lightbox assetId={openId} onClose={() => setOpenId(null)} onNavigate={setOpenId} />}
      {toastMsg && <div className="toast">{toastMsg}</div>}
      {ctx.error && <div className="toast bad">{ctx.error}</div>}
    </BoardContext.Provider>
  );
}

function LibraryPanel() {
  const { board, openAsset } = useBoard();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<Kind | "approved" | "all">("approved");
  if (!board) return null;
  const kindOf = new Map(board.cards.map((c) => [c.id, c.kind]));
  const heroes = new Set(board.cards.map((c) => c.hero_asset_id));
  const items = board.assets.filter((a) =>
    filter === "all" ? true : filter === "approved" ? heroes.has(a.id) : kindOf.get(a.card_id ?? "") === filter,
  );
  const title = (cardId: string | null) => board.cards.find((c) => c.id === cardId)?.title || "Untitled";
  return (
    <>
      <button className="library-toggle" onClick={() => setOpen(!open)}>
        {open ? "Close library" : `Library · ${board.assets.length}`}
      </button>
      {open && (
        <aside className="library">
          <div className="tabs">
            {(["approved", "character", "scene", "prop", "all"] as const).map((f) => (
              <button key={f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>
                {f === "approved" ? "★ Approved" : f === "all" ? "All" : KIND_LABEL[f]}
              </button>
            ))}
          </div>
          <div className="grid">
            {items.map((a) => (
              <button key={a.id} className="tile" onClick={() => openAsset(a.id)}>
                <img src={thumbUrl(a)} alt="" loading="lazy" />
                <span className={`tile-label kind-${kindOf.get(a.card_id ?? "")}`}>{title(a.card_id)}</span>
              </button>
            ))}
            {items.length === 0 && <div className="muted small">Nothing here yet.</div>}
          </div>
        </aside>
      )}
    </>
  );
}

export default function App() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectId, setProjectId] = useState<string | null>(readLast());
  const [engine, setEngine] = useState<Engine | null>(null);
  const [busy, setBusy] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [addCard, setAddCard] = useState<((k: Kind) => void) | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const registerAdd = useCallback((fn: (k: Kind) => void) => setAddCard(() => fn), []);

  const loadProjects = useCallback(async () => {
    const ps = await api.projects();
    setProjects(ps);
    setProjectId((cur) => (cur && ps.some((p) => p.id === cur) ? cur : (ps[0]?.id ?? null)));
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    try {
      if (projectId) localStorage.setItem(LAST_PROJECT, projectId);
    } catch {
      /* private mode */
    }
  }, [projectId]);

  useEffect(() => {
    let t: number;
    const poll = async () => {
      try {
        const e = await api.engine();
        setEngine(e);
        setBusy(e.online ? (e.queue_running ?? 0) + (e.queue_pending ?? 0) : 0);
      } catch {
        setEngine({ online: false, url: "", error: "H3 Canvas backend not running" });
      }
      t = window.setTimeout(poll, 8000);
    };
    poll();
    return () => clearTimeout(t);
  }, []);

  const newProject = async () => {
    const name = prompt("Project name", "Untitled film");
    if (!name) return;
    const p = await api.createProject(name);
    await loadProjects();
    setProjectId(p.id);
  };

  const project = projects?.find((p) => p.id === projectId) ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">H3</span> Canvas
        </div>
        {projects && projects.length > 0 && (
          <select className="project-select" value={projectId ?? ""} onChange={(e) => setProjectId(e.target.value)}>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        <button onClick={newProject}>+ Project</button>
        <div className="spacer" />
        <EnginePill engine={engine} busy={busy} onClick={() => setShowSettings(true)} />
        <button onClick={() => setShowSettings(true)}>Settings</button>
      </header>

      {projectId && (
        <nav className="dock">
          {(["character", "scene", "prop"] as Kind[]).map((k) => (
            <button key={k} className={`add-btn kind-${k}`} onClick={() => addCard?.(k)} title={`Add ${KIND_LABEL[k]}`}>
              <span className="plus">+</span>
              {KIND_LABEL[k]}
            </button>
          ))}
        </nav>
      )}

      <main className="stage">
        {projects && !projectId && (
          <div className="empty-hint">
            <h2>Welcome to H3 Canvas</h2>
            <p>Your laptop holds the projects and assets. The PC at home only renders.</p>
            <button className="primary" onClick={newProject}>
              Create your first project
            </button>
          </div>
        )}
        {projectId && (
          <ReactFlowProvider key={`${projectId}-${reloadKey}`}>
            <Canvas projectId={projectId} onAdd={registerAdd} />
          </ReactFlowProvider>
        )}
      </main>

      {showSettings && (
        <SettingsDialog
          project={project}
          onClose={() => setShowSettings(false)}
          onSaved={() => {
            loadProjects();
            setReloadKey((k) => k + 1);
          }}
          onDeleteProject={async () => {
            if (!project) return;
            if (!confirm(`Delete "${project.name}" and all its images from this laptop? This cannot be undone.`)) return;
            await api.deleteProject(project.id);
            setShowSettings(false);
            setProjectId(null);
            await loadProjects();
          }}
        />
      )}
    </div>
  );
}
