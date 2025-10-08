import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { PropsWithChildren } from "react"
import { fetchBatchSummary, fetchQueueBatches, mapBatchStatus } from "../api/client"
import type { BatchSummary, UiBatchState } from "../api/types"

type BatchCache = Map<string, BatchSummary>

interface BatchStoreState {
  history: BatchSummary[]
  historyStatus: "idle" | "loading" | "error"
  refreshHistory: () => Promise<void>
  getBatch: (batchId: string, force?: boolean) => Promise<BatchSummary | null>
  getCachedBatch: (batchId: string) => BatchSummary | null
  statusFor: (status: BatchSummary["status"]) => UiBatchState
}

const BatchStoreContext = createContext<BatchStoreState | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export const useBatchStore = () => {
  const store = useContext(BatchStoreContext)
  if (!store) {
    throw new Error("useBatchStore must be used within a BatchStoreProvider")
  }
  return store
}

export const BatchStoreProvider = ({ children }: PropsWithChildren) => {
  const [history, setHistory] = useState<BatchSummary[]>([])
  const [historyStatus, setHistoryStatus] = useState<"idle" | "loading" | "error">("idle")
  const cacheRef = useRef<BatchCache>(new Map())

  const refreshHistory = useCallback(async () => {
    setHistoryStatus("loading")
    try {
      const items = await fetchQueueBatches()
      setHistory(items)
      for (const item of items) {
        cacheRef.current.set(item.id, item)
      }
      setHistoryStatus("idle")
    } catch (error) {
      console.error("Failed to load batches", error)
      setHistoryStatus("error")
    }
  }, [])

  useEffect(() => {
    refreshHistory().catch(() => undefined)
  }, [refreshHistory])

  const getBatch = useCallback(async (batchId: string, force = false) => {
    if (!force && cacheRef.current.has(batchId)) {
      return cacheRef.current.get(batchId) ?? null
    }
    try {
      const summary = await fetchBatchSummary(batchId)
      cacheRef.current.set(batchId, summary)
      return summary
    } catch (error) {
      console.error("Failed to load batch", batchId, error)
      return null
    }
  }, [])

  const getCachedBatch = useCallback((batchId: string) => {
    return cacheRef.current.get(batchId) ?? null
  }, [])

  const value = useMemo<BatchStoreState>(
    () => ({
      history,
      historyStatus,
      refreshHistory,
      getBatch,
      getCachedBatch,
      statusFor: mapBatchStatus,
    }),
    [getBatch, getCachedBatch, history, historyStatus, refreshHistory],
  )

  return <BatchStoreContext.Provider value={value}>{children}</BatchStoreContext.Provider>
}
