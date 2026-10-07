import { useEffect } from "react";
import { api, fileUrl, KIND_LABEL, type Asset } from "../api";
import { useBoard } from "../board";

export function Lightbox({ assetId, onClose, onNavigate }: { assetId: string; onClose: () => void; onNavigate: (id: string) => void }) {
  const { board, refresh, toast } = useBoard();
  const asset = board?.assets.find((a) => a.id === assetId);
  const card = board?.cards.find((c) => c.id === asset?.card_id);
  // Siblings: same card (or the whole library for orphans), oldest first.
  const siblings: Asset[] = (board?.assets ?? []).filter((a) => a.card_id === asset?.card_id).reverse();
  const idx = siblings.findIndex((a) => a.id === assetId);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft" && idx > 0) onNavigate(siblings[idx - 1].id);
      if (e.key === "ArrowRight" && idx < siblings.length - 1) onNavigate(siblings[idx + 1].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, siblings, onClose, onNavigate]);

  if (!asset) return null;
  const isHero = card?.hero_asset_id === asset.id;

  const setHero = async () => {
    if (!card) return;
    await api.patchCard(card.id, { hero_asset_id: asset.id });
    await refresh();
  };

  const remove = async () => {
    if (!confirm("Delete this image from the laptop?")) return;
    const next = siblings[idx + 1] ?? siblings[idx - 1];
    await api.deleteAsset(asset.id);
    await refresh();
    if (next) onNavigate(next.id);
    else onClose();
  };

  return (
    <div className="lightbox" onClick={onClose}>
      <div className="lightbox-body" onClick={(e) => e.stopPropagation()}>
        <div className="lightbox-media">
          {idx > 0 && (
            <button className="nav prev" onClick={() => onNavigate(siblings[idx - 1].id)}>
              ‹
            </button>
          )}
          {asset.media === "video" ? <video src={fileUrl(asset)} controls autoPlay loop /> : <img src={fileUrl(asset)} alt="" />}
          {idx < siblings.length - 1 && (
            <button className="nav next" onClick={() => onNavigate(siblings[idx + 1].id)}>
              ›
            </button>
          )}
        </div>
        <aside className="lightbox-side">
          <div className="side-head">
            <div>
              <div className="muted small">{card ? KIND_LABEL[card.kind] : "Asset"}</div>
              <h3>{card?.title || "Untitled"}</h3>
            </div>
            <button className="icon-btn" onClick={onClose}>
              ✕
            </button>
          </div>
          <div className="muted small">
            {idx + 1} / {siblings.length} · {asset.width}×{asset.height} · seed {asset.seed ?? "?"}
          </div>
          <div className="actions">
            <button className={isHero ? "primary" : ""} onClick={setHero} disabled={isHero || !card}>
              {isHero ? "★ Approved" : "☆ Approve as reference"}
            </button>
            <a className="button" href={fileUrl(asset)} download>
              Download
            </a>
            <button className="danger" onClick={remove}>
              Delete
            </button>
          </div>
          <label className="muted small">Prompt</label>
          <pre className="prompt">{asset.prompt}</pre>
          <button
            onClick={() => {
              navigator.clipboard.writeText(asset.prompt);
              toast("Prompt copied");
            }}
          >
            Copy prompt
          </button>
          <div className="muted small">
            {asset.workflow} · {new Date(asset.created_at * 1000).toLocaleString()}
          </div>
        </aside>
      </div>
    </div>
  );
}
