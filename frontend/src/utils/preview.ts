export const buildPreviewCandidates = (batchId: string, docId: string, page?: number | null): string[] => {
  const safePage = page && page > 0 ? page : 1
  const pagePadded = String(safePage).padStart(3, "0")
  const baseNames = [
    `page-${safePage}`,
    `page-${pagePadded}`,
    `page_${safePage}`,
    `page_${pagePadded}`,
    `preview-${safePage}`,
    `preview-${pagePadded}`,
  ]
  const extensions = ["png", "jpg", "jpeg", "webp"]
  const urls: string[] = []
  const seen = new Set<string>()
  for (const base of baseNames) {
    for (const ext of extensions) {
      const candidate = `/files/batches/${batchId}/preview/${docId}/${base}.${ext}`
      if (!seen.has(candidate)) {
        seen.add(candidate)
        urls.push(candidate)
      }
    }
  }
  return urls
}

export const getPrimaryPreview = (batchId: string, docId: string, page?: number | null): string | null => {
  const candidates = buildPreviewCandidates(batchId, docId, page)
  return candidates[0] ?? null
}

