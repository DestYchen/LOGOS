import { useState } from 'react'
import type React from 'react'
import pdfIcon from './assets/pdf_icon.png'
import wordIcon from './assets/word_icon.png'
import excelIcon from './assets/excel_icon.png'
import otherIcon from './assets/other_icon.png'

const App = () => {
  const [isDragging, setIsDragging] = useState(false)
  const [files, setFiles] = useState<File[]>([])

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }
  const onDragLeave = () => setIsDragging(false)
  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer?.files?.length) {
      setFiles((prev) => [...prev, ...Array.from(e.dataTransfer.files)])
    }
  }
  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.currentTarget.files?.length) setFiles((prev) => [...prev, ...Array.from(e.currentTarget.files!)])
    e.currentTarget.value = ''
  }

  const kindOf = (name: string) => {
    const lower = name.toLowerCase()
    if (lower.endsWith('.pdf')) return 'pdf' as const
    if (lower.endsWith('.doc') || lower.endsWith('.docx')) return 'word' as const
    if (lower.endsWith('.xls') || lower.endsWith('.xlsx') || lower.endsWith('.csv')) return 'excel' as const
    return 'other' as const
  }
  const iconFor = (name: string) => {
    const k = kindOf(name)
    return k === 'pdf' ? pdfIcon : k === 'word' ? wordIcon : k === 'excel' ? excelIcon : otherIcon
  }

  return (
    <div className='page'>
      <div className='upload-shell'>
        <div
          className={`dz-card ${isDragging ? 'is-dragging' : ''} ${files.length ? 'has-files' : ''}`}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          <input id='file-input' type='file' multiple onChange={onPick} />

          {files.length === 0 ? (
            <div className='dz-empty'>
              <div className='icons-row'>
                <div className='icon-ghost left' />
                <div className='icon-ghost center' />
                <div className='icon-ghost right' />
              </div>
              <h2 className='dz-title'>Перетащите документы <span className='accent-blue'>Word</span>, <span className='accent-purple'>Excel</span> или <span className='accent-red'>PDF</span></h2>
              <p className='dz-sub'>или <label htmlFor='file-input' className='link'>выберите файлы</label> на компьютере</p>
            </div>
          ) : (
            <div className='icon-grid'>
              {files.map((f, i) => (
                <div key={`${f.name}-${i}`} className='icon-item' title={f.name}>
                  <img src={iconFor(f.name)} alt='' className='doc-icon-large' />
                  <div className='doc-name'>{f.name}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className='controls'>
          <button className='btn-upload' type='button' disabled={!files.length}>Загрузить</button>
        </div>
      </div>
    </div>
  )
}

export default App
