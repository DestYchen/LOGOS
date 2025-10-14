import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { fetchBatches } from "../lib/api";
import type { BatchSummary } from "../types/api";

type HistoryContextValue = {
  batches: BatchSummary[];
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
  markAsRecent: (batchId: string | null) => void;
  recentBatchId: string | null;
};

const HistoryContext = createContext<HistoryContextValue | undefined>(undefined);

export function HistoryProvider({ children }: { children: React.ReactNode }) {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const [recentBatchId, setRecentBatchId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchBatches();
      setBatches(response.batches);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const markAsRecent = useCallback((batchId: string | null) => {
    setRecentBatchId(batchId);
  }, []);

  const value = useMemo<HistoryContextValue>(
    () => ({
      batches,
      loading,
      error,
      refresh: load,
      markAsRecent,
      recentBatchId,
    }),
    [batches, loading, error, load, markAsRecent, recentBatchId],
  );

  return <HistoryContext.Provider value={value}>{children}</HistoryContext.Provider>;
}

export function useHistoryContext(): HistoryContextValue {
  const ctx = useContext(HistoryContext);
  if (!ctx) {
    throw new Error("useHistoryContext must be used within HistoryProvider");
  }
  return ctx;
}
