export type Kind = "character" | "scene" | "prop";

export interface Project {
  id: string;
  name: string;
  style: string;
  negative: string;
  templates: Record<Kind, string>;
  image_workflow: string;
  card_count?: number;
}

export interface Card {
  id: string;
  project_id: string;
  kind: Kind;
  title: string;
  description: string;
  aspect: string;
  x: number;
  y: number;
  hero_asset_id: string | null;
}

export interface Asset {
  id: string;
  project_id: string;
  card_id: string | null;
  media: "image" | "video" | "file";
  file: string;
  thumb: string | null;
  width: number | null;
  height: number | null;
  prompt: string;
  seed: number | null;
  workflow: string;
  created_at: number;
}

export type JobStatus = "pending" | "queued" | "running" | "done" | "error";

export interface Job {
  id: string;
  card_id: string | null;
  workflow: string;
  status: JobStatus;
  error: string | null;
  seed: number | null;
  created_at: number;
}

export interface Board {
  project: Project;
  cards: Card[];
  assets: Asset[];
  jobs: Job[];
  engine: { online: boolean | null; error: string | null; busy: number };
}

export interface Settings {
  comfy_url: string;
  keep_pc_clean: boolean;
  wait_for_idle: boolean;
  data_dir: string;
  workflow_dir: string;
  aspects: Record<string, [number, number]>;
  kinds: Kind[];
}

export interface Engine {
  online: boolean;
  url: string;
  error?: string;
  comfyui_version?: string;
  queue_running?: number;
  queue_pending?: number;
  devices?: { name: string; vram_total: number; vram_free: number }[];
}

export interface WorkflowInfo {
  name: string;
  file?: string;
  output?: string;
  mapping_source?: string;
  mapping?: Record<string, [string, string][]>;
  missing?: string[];
  error?: string;
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* keep status text */
    }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  settings: () => req<Settings>("GET", "/api/settings"),
  saveSettings: (s: Partial<Settings>) => req<Settings>("PUT", "/api/settings", s),
  engine: () => req<Engine>("GET", "/api/engine"),
  workflows: () => req<WorkflowInfo[]>("GET", "/api/workflows"),
  projects: () => req<Project[]>("GET", "/api/projects"),
  createProject: (name: string) => req<Project>("POST", "/api/projects", { name }),
  patchProject: (id: string, p: Partial<Project>) => req<Project>("PATCH", `/api/projects/${id}`, p),
  deleteProject: (id: string) => req("DELETE", `/api/projects/${id}`),
  board: (id: string) => req<Board>("GET", `/api/projects/${id}/board`),
  createCard: (pid: string, c: Partial<Card>) => req<Card>("POST", `/api/projects/${pid}/cards`, c),
  patchCard: (id: string, c: Partial<Card>) => req<Card>("PATCH", `/api/cards/${id}`, c),
  deleteCard: (id: string) => req("DELETE", `/api/cards/${id}`),
  promptPreview: (id: string) => req<{ prompt: string }>("GET", `/api/cards/${id}/prompt`),
  generate: (id: string, count: number) => req<Job[]>("POST", `/api/cards/${id}/generate`, { count }),
  cancelJob: (id: string) => req("DELETE", `/api/jobs/${id}`),
  deleteAsset: (id: string) => req("DELETE", `/api/assets/${id}`),
};

export const fileUrl = (a: Asset) => `/files/${a.project_id}/${a.file}`;
export const thumbUrl = (a: Asset) => (a.thumb ? `/files/${a.project_id}/${a.thumb}` : fileUrl(a));

export const KIND_LABEL: Record<Kind, string> = {
  character: "Character",
  scene: "Scene",
  prop: "Prop",
};
