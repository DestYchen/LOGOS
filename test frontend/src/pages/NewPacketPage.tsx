
import { ChangeEvent, DragEvent, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { FileTile, type FileEntry } from "../components/upload/FileTile";
import { UploadIllustration } from "../components/upload/file-assets";
import { useHistoryContext } from "../contexts/history-context";
import { uploadDocuments } from "../lib/api";
import { cn } from "../lib/utils";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Spinner } from "../components/ui/spinner";

const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024;
const SUPPORTED_EXT = ["pdf", "doc", "docx", "xls", "xlsx", "txt", "png", "jpg", "jpeg"];

type ListedFile = {
  id: string;
  file: File;
  error?: string;
};

function validateFile(file: File, existing: ListedFile[]) {
  const errors: string[] = [];
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!SUPPORTED_EXT.includes(ext)) {
    errors.push("Неподдерживаемый формат");
  }
  if (file.size > MAX_FILE_SIZE) {
    errors.push(`Файл больше ${MAX_FILE_SIZE_MB} МБ`);
  }
  const duplicate = existing.some((entry) => entry.file.name === file.name && entry.file.size === file.size);
  if (duplicate) {
    errors.push("Файл уже добавлен");
  }
  return errors;
}

function formatSize(size: number) {
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

function NewPacketPage() {
  const navigate = useNavigate();
  const { markAsRecent } = useHistoryContext();
  const [items, setItems] = useState<ListedFile[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const validFiles = useMemo(() => items.filter((item) => !item.error).map((item) => item.file), [items]);
  const displayItems: FileEntry[] = useMemo(
    () =>
      items.map((item) => ({
        id: item.id,
        name: item.file.name,
        size: item.file.size,
        meta: formatSize(item.file.size),
        error: item.error,
      })),
    [items],
  );

  const appendFiles = (files: File[]) => {
    setItems((previous) => {
      const next = [...previous];
      files.forEach((file) => {
        const issues = validateFile(file, next);
        next.push({
          id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
          file,
          error: issues.length ? issues.join(", ") : undefined,
        });
      });
      return next;
    });
    setError(null);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
    const dropped = Array.from(event.dataTransfer.files || []);
    appendFiles(dropped);
  };

  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(true);
  };

  const onDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget === event.target) {
      setDragActive(false);
    }
  };

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files || []);
    appendFiles(selected);
    event.target.value = "";
  };

  const removeFile = (id: string) => {
    setItems((prev) => prev.filter((entry) => entry.id !== id));
  };

  const handleUpload = async () => {
    if (!validFiles.length) {
      setError("Добавьте хотя бы один поддерживаемый файл.");
      return;
    }
    try {
      setUploading(true);
      const response = await uploadDocuments(validFiles);
      markAsRecent(response.batch_id);
      navigate(`/queue?batch=${response.batch_id}`, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-4xl flex-col items-center justify-center gap-10">
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={cn(
          "w-full rounded-3xl border-2 border-dashed border-primary/40 bg-background/95 p-8 shadow-xl transition-colors",
          dragActive && "border-primary bg-primary/5",
        )}
      >
        <div className="flex min-h-[320px] flex-col items-center justify-center gap-6">
          {items.length === 0 ? (
            <>
              <UploadIllustration className="h-24" />
              <p className="text-lg font-semibold text-muted-foreground">
                Загрузите файлы PDF, Word, Excel или картинки
              </p>
              <Button variant="secondary" onClick={() => inputRef.current?.click()}>
                Выбрать файлы
              </Button>
            </>
          ) : (
            <div className="grid w-full gap-4 sm:grid-cols-2 md:grid-cols-3">
              {displayItems.map((item) => (
                <FileTile key={item.id} item={item} onRemove={removeFile} />
              ))}
            </div>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.png,.jpg,.jpeg"
          onChange={onInputChange}
        />
      </div>
      <div className="flex items-center gap-4">
        {uploading ? <Spinner /> : null}
        <Button onClick={handleUpload} disabled={uploading || !validFiles.length}>
          Продолжить
        </Button>
      </div>
      {error ? <Alert variant="destructive">{error}</Alert> : null}
    </div>
  );
}

export default NewPacketPage;
