import { useEffect, useMemo, useState } from "react"

interface ViewerBox {
  key: string
  bbox: number[] | null
  label?: string
  active?: boolean
}

interface DocumentViewerProps {
  imageUrl?: string | null
  imageCandidates?: string[]
  title?: string
  boxes?: ViewerBox[]
  onHoverBox?: (key: string | null) => void
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

const deriveBoxStyle = (
  bbox: number[],
  natural: { width: number; height: number } | null,
): { left: string; top: string; width: string; height: string } | null => {
  if (bbox.length < 4) return null
  if (!natural || !natural.width || !natural.height) {
    if (bbox.every((value) => value <= 1)) {
      const [x, y, w, h] = bbox
      const width = bbox[2] >= x ? bbox[2] - x : w
      const height = bbox[3] >= y ? bbox[3] - y : h
      return {
        left: `${clamp(x, 0, 1) * 100}%`,
        top: `${clamp(y, 0, 1) * 100}%`,
        width: `${clamp(width, 0, 1) * 100}%`,
        height: `${clamp(height, 0, 1) * 100}%`,
      }
    }
    return null
  }
  const [rawX, rawY, rawW, rawH] = bbox
  const x1 = rawX
  const y1 = rawY
  let widthVal = rawW
  let heightVal = rawH
  if (rawW > rawX && rawH > rawY) {
    widthVal = rawW - rawX
    heightVal = rawH - rawY
  }
  const left = clamp(x1 / natural.width, 0, 1)
  const top = clamp(y1 / natural.height, 0, 1)
  const width = clamp(widthVal / natural.width, 0, 1)
  const height = clamp(heightVal / natural.height, 0, 1)
  return {
    left: `${left * 100}%`,
    top: `${top * 100}%`,
    width: `${width * 100}%`,
    height: `${height * 100}%`,
  }
}

const DocumentViewer = ({ imageUrl = null, imageCandidates = [], title, boxes = [], onHoverBox }: DocumentViewerProps) => {
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null)
  const [zoomOrigin, setZoomOrigin] = useState<{ x: number; y: number }>({ x: 50, y: 50 })
  const [zooming, setZooming] = useState(false)
  const [sourceIndex, setSourceIndex] = useState(0)

  const sources = useMemo(() => {
    const seen = new Set<string>()
    const ordered: string[] = []
    const add = (value: string | null | undefined) => {
      if (!value) return
      if (seen.has(value)) return
      seen.add(value)
      ordered.push(value)
    }
    add(imageUrl)
    for (const candidate of imageCandidates) {
      add(candidate)
    }
    return ordered
  }, [imageCandidates, imageUrl])

  const sourcesKey = useMemo(() => sources.join("|"), [sources])

  useEffect(() => {
    setSourceIndex(0)
    setNaturalSize(null)
  }, [sourcesKey])

  const activeImage = sources[sourceIndex] ?? null

  const handleImageError = () => {
    if (sourceIndex < sources.length - 1) {
      setNaturalSize(null)
      setSourceIndex((prev) => prev + 1)
    } else {
      setSourceIndex(sources.length)
    }
  }

  const preparedBoxes = useMemo(() => {
    if (!activeImage) return []
    return boxes
      .filter((box) => Array.isArray(box.bbox) && box.bbox.length >= 4)
      .map((box) => ({
        ...box,
        style: deriveBoxStyle(box.bbox!, naturalSize),
      }))
      .filter((box) => box.style !== null)
  }, [activeImage, boxes, naturalSize])

  return (
    <div className="resolve-viewer">
      <div className="viewer-header">
        <div className="viewer-title">{title ?? ""}</div>
        {zooming && <div className="viewer-zoom-indicator">×2</div>}
      </div>
      <div
        className={`viewer-stage${zooming ? " is-zoom" : ""}`}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect()
          const x = clamp(((event.clientX - rect.left) / rect.width) * 100, 0, 100)
          const y = clamp(((event.clientY - rect.top) / rect.height) * 100, 0, 100)
          setZoomOrigin({ x, y })
          setZooming(true)
        }}
        onMouseLeave={() => {
          setZooming(false)
          setZoomOrigin({ x: 50, y: 50 })
          onHoverBox?.(null)
        }}
        style={
          {
            "--zoom-x": `${zoomOrigin.x}%`,
            "--zoom-y": `${zoomOrigin.y}%`,
          } as React.CSSProperties
        }
      >
        {activeImage ? (
          <>
            <img
              src={activeImage}
              alt={title ?? ""}
              className="viewer-image"
              onLoad={(event) => {
                const img = event.currentTarget
                setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight })
              }}
              onError={handleImageError}
            />
            <div className="viewer-boxes">
              {preparedBoxes.map((box) => (
                <button
                  key={box.key}
                  type="button"
                  className={`viewer-box${box.active ? " is-active" : ""}`}
                  style={box.style ?? undefined}
                  onMouseEnter={() => onHoverBox?.(box.key)}
                  onFocus={() => onHoverBox?.(box.key)}
                  onMouseLeave={() => onHoverBox?.(null)}
                >
                  {box.label && <span className="viewer-box-label">{box.label}</span>}
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="viewer-empty">{"\u041d\u0435\u0442 \u043f\u0440\u0435\u0432\u044c\u044e \u0434\u043b\u044f \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430"}</div>
        )}
        <div className="viewer-lens" />
      </div>
    </div>
  )
}

export type { ViewerBox }
export default DocumentViewer


