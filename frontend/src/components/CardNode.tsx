import { memo, useEffect, useState } from "react";
import type { NodeProps } from "@xyflow/react";
import { api, KIND_LABEL, thumbUrl, type Asset, type Job } from "../api";
import { useBoard } from "../board";

const ASPECTS = ["2:3", "3:4", "1:1", "4:3", "3:2", "16:9", "9:16"];

const STATUS_LABEL: Record<string, string> = {
  pending: "waiting",
  queued: "queued",
  running: "rendering",
  error: "failed",
};

function ratio(aspect: string) {
  const [w, h] = aspect.split(":").map(Number);
  return w && h ? `${w} / ${h}` : "1 / 1";
}

export const CardNode = memo(function CardNode({ data, selected }: NodeProps) {
  const cardId = (data as { cardId: string }).cardId;
  const { board, refresh, openAsset, toast } = useBoard();
  const card = board?.cards.find((c) => c.id === cardId);
  const [title, setTitle] = useState(card?.title ?? "");
  const [desc, setDesc] = useState(card?.description ?? "");
  const [count, setCount] = useState(2);
  const [busy, setBusy] = useState(false);

  // Pick up server-side changes unless the user is mid-edit.
  useEffect(() => {
    if (card && document.activeElement?.closest(`[data-card="${cardId}"]`) == null) {
      setTitle(card.title);
      setDesc(card.description);
    }
  }, [card?.title, card?.description]);

  if (!card || !board) return null;

  const assets: Asset[] = board.assets.filter((a) => a.card_id === card.id);
  const jobs: Job[] = board.jobs.filter((j) => j.card_id === card.id);
  const hero = assets.find((a) => a.id === card.hero_asset_id) ?? assets[0];
  const heroJob = !hero ? jobs.find((j) => j.status !== "error") : undefined;

  const save = async (fields: Partial<typeof card>) => {
    try {
      await api.patchCard(card.id, fields);
      await refresh();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const generate = async () => {
    setBusy(true);
    try {
      if (title !== card.title || desc !== card.description) {
        await api.patchCard(card.id, { title, description: desc });
      }
      await api.generate(card.id, count);
      await refresh();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete "${card.title || KIND_LABEL[card.kind]}" and its ${assets.length} image(s) from this laptop?`)) return;
    await api.deleteCard(card.id);
    await refresh();
  };

  return (
    <div className={`card kind-${card.kind} ${selected ? "selected" : ""}`} data-card={card.id}>
      <div className="card-head">
        <span className="kind-badge">{KIND_LABEL[card.kind]}</span>
        <input
          className="card-title nodrag"
          value={title}
          placeholder={`Name this ${card.kind}`}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title !== card.title && save({ title })}
        />
        <button className="icon-btn nodrag" title="Delete card" onClick={remove}>
          ✕
        </button>
      </div>

      <div className="hero" style={{ aspectRatio: ratio(card.aspect) }}>
        {hero ? (
          hero.media === "video" ? (
            <video src={`/files/${hero.project_id}/${hero.file}`} muted loop autoPlay playsInline />
          ) : (
            <img src={thumbUrl(hero)} alt="" draggable={false} onDoubleClick={() => openAsset(hero.id)} onClick={() => openAsset(hero.id)} />
          )
        ) : heroJob ? (
          <div className="hero-empty">
            <div className="spinner" />
            <span>{STATUS_LABEL[heroJob.status]}</span>
          </div>
        ) : (
          <div className="hero-empty">
            <span>Describe it below, then Generate</span>
          </div>
        )}
        {hero && hero.id === card.hero_asset_id && <span className="hero-pin">★ approved</span>}
      </div>

      {(assets.length > 0 || jobs.length > 0) && (
        <div className="variants nodrag nowheel">
          {assets.map((a) => (
            <button
              key={a.id}
              className={`variant ${a.id === hero?.id ? "active" : ""}`}
              onClick={() => openAsset(a.id)}
              title={`seed ${a.seed ?? "?"}`}
            >
              <img src={thumbUrl(a)} alt="" draggable={false} />
            </button>
          ))}
          {jobs.map((j) => (
            <button
              key={j.id}
              className={`variant job job-${j.status}`}
              title={j.error ?? `${STATUS_LABEL[j.status]} · seed ${j.seed}`}
              onClick={async () => {
                const what = j.status === "error" ? `Dismiss this error?\n\n${j.error}` : "Cancel this job?";
                if (confirm(what)) {
                  await api.cancelJob(j.id);
                  await refresh();
                }
              }}
            >
              {j.status === "error" ? "!" : <div className="spinner small" />}
            </button>
          ))}
        </div>
      )}

      <textarea
        className="card-desc nodrag nowheel"
        value={desc}
        rows={3}
        placeholder={
          card.kind === "character"
            ? "Look, age, face, hair, outfit…"
            : card.kind === "scene"
              ? "Place, era, time of day, light, mood…"
              : "Object, material, size, details…"
        }
        onChange={(e) => setDesc(e.target.value)}
        onBlur={() => desc !== card.description && save({ description: desc })}
      />

      <div className="card-foot nodrag">
        <select value={card.aspect} onChange={(e) => save({ aspect: e.target.value })} title="Aspect ratio">
          {ASPECTS.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <select value={count} onChange={(e) => setCount(Number(e.target.value))} title="Variants">
          {[1, 2, 4].map((n) => (
            <option key={n} value={n}>
              ×{n}
            </option>
          ))}
        </select>
        <button className="primary" disabled={busy || (!desc.trim() && !title.trim())} onClick={generate}>
          {busy ? "…" : "Generate"}
        </button>
      </div>
    </div>
  );
});
