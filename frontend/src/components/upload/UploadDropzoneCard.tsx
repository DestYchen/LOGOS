import { useRef } from "react"
import type { ReactNode } from "react"
import pdfIcon from "../../assets/pdf_icon.png"
import wordIcon from "../../assets/word_icon.png"
import excelIcon from "../../assets/excel_icon.png"
import otherIcon from "../../assets/other_icon.png"

export type UploadIcon = "pdf" | "word" | "excel" | "other"

export interface UploadDisplayItem {
  id: string
  name: string
  sizeLabel?: string
  meta?: string
  icon: UploadIcon
  removable?: boolean
}

export interface UploadDropzoneCardProps {
  items: UploadDisplayItem[]
  dragging?: boolean
  disabled?: boolean
  highlight?: "default" | "queue"
  placeholder?: ReactNode
  hint?: ReactNode
  footer?: ReactNode
  onPickFiles?: (files: File[]) => void
  onDropFiles?: (files: File[]) => void
  onRemoveItem?: (id: string) => void
  onDragEnter?: () => void
  onDragLeave?: () => void
}

const iconMap: Record<UploadIcon, string> = {
  pdf: pdfIcon,
  word: wordIcon,
  excel: excelIcon,
  other: otherIcon,
}

const UploadDropzoneCard = ({
  items,
  dragging = false,
  disabled = false,
  highlight = "default",
  placeholder,
  hint,
  footer,
  onPickFiles,
  onDropFiles,
  onRemoveItem,
  onDragEnter,
  onDragLeave,
}: UploadDropzoneCardProps) => {
  const inputRef = useRef<HTMLInputElement | null>(null)

  const handlePick = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!onPickFiles) return
    const files = event.target.files
    if (files && files.length) {
      onPickFiles(Array.from(files))
    }
    event.target.value = ""
  }

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    if (disabled || !onDropFiles) return
    event.preventDefault()
    onDragLeave?.()
    const files = event.dataTransfer?.files
    if (files && files.length) {
      onDropFiles(Array.from(files))
    }
  }

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    if (disabled) return
    event.preventDefault()
  }

  const handleDragEnter = (event: React.DragEvent<HTMLDivElement>) => {
    if (disabled) return
    event.preventDefault()
    onDragEnter?.()
  }

  const handleDragLeave = (event: React.DragEvent<HTMLDivElement>) => {
    if (disabled) return
    event.preventDefault()
    onDragLeave?.()
  }

  const handleClick = () => {
    if (disabled || !onPickFiles) return
    inputRef.current?.click()
  }

  return (
    <div className="upload-card-shell">
      <div
        className={[
          "upload-dropzone",
          highlight === "queue" ? "is-queue" : "",
          dragging ? "is-dragging" : "",
          disabled ? "is-disabled" : "",
        ].join(" ")}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onClick={handleClick}
      >
        {onPickFiles && (
          <input
            ref={inputRef}
            type="file"
            multiple
            onChange={handlePick}
            disabled={disabled}
            className="upload-input"
            aria-hidden="true"
          />
        )}
        {items.length === 0 ? (
          <div className="upload-placeholder">
            {placeholder}
            {hint}
          </div>
        ) : (
          <div className="upload-items">
            {items.map((item) => (
              <div key={item.id} className="upload-item">
                <img src={iconMap[item.icon]} alt="" className="upload-item-icon" />
                <div className="upload-item-body">
                  <span className="upload-item-name" title={item.name}>
                    {item.name}
                  </span>
                  {item.sizeLabel && (
                    <span className="upload-item-meta" title={item.sizeLabel}>
                      {item.sizeLabel}
                    </span>
                  )}
                  {item.meta && (
                    <span className="upload-item-meta" title={item.meta}>
                      {item.meta}
                    </span>
                  )}
                </div>
                {item.removable && onRemoveItem && (
                  <button type="button" className="upload-item-remove" onClick={() => onRemoveItem(item.id)}>
                    {"\u00d7"}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      {footer}
    </div>
  )
}

export default UploadDropzoneCard
