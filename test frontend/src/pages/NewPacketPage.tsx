import { ChangeEvent, DragEvent, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import pdfIcon from "../assets/pdf_icon.png";
import wordIcon from "../assets/word_icon.png";
import excelIcon from "../assets/excel_icon.png";
import otherIcon from "../assets/other_icon.png";
import { useHistoryContext } from "../contexts/history-context";
import { uploadDocuments } from "../lib/api";
import { cn } from "../lib/utils";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "../components/ui/card";
import { Spinner } from "../components/ui/spinner";

const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024;
const SUPPORTED_EXT = ["pdf", "doc", "docx", "xls", "xlsx", "txt"];

type ListedFile = {
  id: string;
  file: File;
  error?: string;
};

function iconForFile(file: File) {
  const ext = file.name.split(".").pop()?.toLowerCase();
  if (!ext) return otherIcon;
  if (ext === "pdf") return pdfIcon;
  if (ext === "doc" || ext === "docx") return wordIcon;
  if (ext === "xls" || ext === "xlsx") return excelIcon;
  return otherIcon;
}

function describeSize(size: number) {
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

function validateFile(file: File, existing: ListedFile[]) {
  const errors: string[] = [];
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
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

function NewPacketPage() {
  const navigate = useNavigate();
  const { markAsRecent } = useHistoryContext();
  const [items, setItems] = useState<ListedFile[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement | null>(null);

  const validFiles = useMemo(() => items.filter((item) => !item.error).map((item) => item.file), [items]);

  const appendFiles = (files: File[]) => {
    setItems((prev) => {
      const next = [...prev];
      files.forEach((file) => {
        const errors = validateFile(file, next);
        next.push({
          id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
          file,
          error: errors.length ? errors.join(", ") : undefined,
        });
      });
      return next;
    });
    setSuccess(null);
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
    setItems((prev) => prev.filter((item) => item.id !== id));
  };

  const handleUpload = async () => {
    if (!validFiles.length) {
      setError("Добавьте хотя бы один поддерживаемый файл.");
      return;
    }
    try {
      setUploading(true);
      setError(null);
      const response = await uploadDocuments(validFiles);
      setSuccess(`Загружено ${response.documents} документ(ов).`);
      setItems([]);
      markAsRecent(response.batch_id);
      navigate(`/queue?batch=${response.batch_id}`, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Новый пакет</h1>
        <p className="max-w-2xl text-muted-foreground">
          Загрузите документы, чтобы создать новый пакет. Поддерживаются PDF, Word, Excel и текстовые файлы.
        </p>
      </header>

      <Card className="mx-auto max-w-3xl border-dashed border-primary/40 bg-background shadow-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-lg">Перетащите файлы сюда</CardTitle>
          <CardDescription>
            или
            <button
              type="button"
              className="ml-1 text-primary underline"
              onClick={() => inputRef.current?.click()}
            >
              Выбрать файлы
            </button>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            className={cn(
              "flex min-h-[220px] flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-colors",
              dragActive ? "border-primary bg-primary/5" : "border-muted-foreground/30",
            )}
          >
            <p className="text-sm text-muted-foreground">
              Перетащите файлы или нажмите «Выбрать файлы» для добавления документов
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              Макс. размер {MAX_FILE_SIZE_MB} МБ на файл. Поддерживаемые форматы: PDF, DOCX, XLSX, TXT.
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              onChange={onInputChange}
              accept=".pdf,.doc,.docx,.xls,.xlsx,.txt"
            />
            <Button className="mt-6" variant="secondary" onClick={() => inputRef.current?.click()}>
              Выбрать файлы
            </Button>
          </div>
        </CardContent>
        <CardFooter className="flex flex-col items-stretch gap-4">
          {items.length > 0 ? (
            <div className="max-h-64 space-y-2 overflow-y-auto">
              {items.map((item) => (
                <div
                  key={item.id}
                  className={cn(
                    "flex items-center justify-between rounded-xl border px-4 py-3",
                    item.error ? "border-destructive/50 bg-destructive/10" : "border-muted bg-muted/40",
                  )}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <img src={iconForFile(item.file)} alt="" className="h-8 w-8" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium" title={item.file.name}>
                        {item.file.name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {describeSize(item.file.size)}
                        {item.error ? ` • ${item.error}` : ""}
                      </p>
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => removeFile(item.id)}>
                    Удалить
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-center text-sm text-muted-foreground">Файлы пока не выбраны.</p>
          )}

          <div className="flex items-center justify-end gap-3">
            {uploading && <Spinner size="sm" />}
            <Button onClick={handleUpload} disabled={uploading || !validFiles.length}>
              Продолжить
            </Button>
          </div>
        </CardFooter>
      </Card>

      <div className="space-y-3">
        {error ? <Alert variant="destructive">{error}</Alert> : null}
        {success ? <Alert variant="success">{success}</Alert> : null}
      </div>
    </div>
  );
}

export default NewPacketPage;
