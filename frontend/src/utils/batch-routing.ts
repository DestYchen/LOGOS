import type { UiBatchState } from "../api/types"

export const routeForStatus = (status: UiBatchState, batchId: string) => {
  if (status === "manual" || status === "processing") {
    return `/resolve/${batchId}`
  }
  if (status === "done" || status === "failed") {
    return `/table/${batchId}`
  }
  return "/queue"
}
