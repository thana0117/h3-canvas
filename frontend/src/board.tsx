import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, type Board } from "./api";

interface BoardCtx {
  board: Board | null;
  refresh: () => Promise<unknown>;
  openAsset: (assetId: string) => void;
  toast: (msg: string) => void;
}

export const BoardContext = createContext<BoardCtx>({
  board: null,
  refresh: async () => {},
  openAsset: () => {},
  toast: () => {},
});

export const useBoard = () => useContext(BoardContext);

/** Polls the board: fast while jobs are in flight, slow otherwise. */
export function useBoardPolling(projectId: string | null) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = useRef(projectId);
  current.current = projectId;

  const refresh = useCallback(async (): Promise<Board | null> => {
    if (!projectId) return null;
    try {
      const b = await api.board(projectId);
      if (current.current === projectId) {
        setBoard(b);
        setError(null);
      }
      return b;
    } catch (e) {
      setError(String((e as Error).message));
      return null;
    }
  }, [projectId]);

  useEffect(() => {
    setBoard(null);
    if (!projectId) return;
    let timer: number;
    let stopped = false;
    const loop = async () => {
      const b = await refresh();
      if (stopped) return;
      const busy = b?.jobs.some((j) => j.status !== "error");
      timer = window.setTimeout(loop, busy ? 1200 : 5000);
    };
    loop();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [projectId, refresh]);

  return { board, error, refresh };
}
