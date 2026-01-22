import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Spinner } from "../components/ui/spinner";
import { Textarea } from "../components/ui/textarea";
import { sendFeedback } from "../lib/api";
import { cn } from "../lib/utils";

const MAX_FILES = 5;
const MAX_FILE_SIZE_MB = 5;
const MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024;
const ACCEPTED_TYPES = ["image/png", "image/jpeg"];
const ACCEPTED_EXT = [".png", ".jpg", ".jpeg"];

type FeedbackLocationState = {
  from?: string;
};

function isAcceptedImage(file: File) {
  if (ACCEPTED_TYPES.includes(file.type)) {
    return true;
  }
  const name = file.name.toLowerCase();
  return ACCEPTED_EXT.some((ext) => name.endsWith(ext));
}

function FeedbackPage() {
  const location = useLocation();
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [feedbackType, setFeedbackType] = useState<"problem" | "improvement">("problem");
  const [contact, setContact] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const origin = useMemo(() => {
    if (location.state && typeof location.state === "object") {
      return (location.state as FeedbackLocationState).from ?? null;
    }
    return null;
  }, [location.state]);

  const previews = useMemo(
    () => files.map((file) => ({ file, url: URL.createObjectURL(file) })),
    [files],
  );
  const fileLimitReached = files.length >= MAX_FILES;

  useEffect(() => {
    return () => {
      previews.forEach((preview) => URL.revokeObjectURL(preview.url));
    };
  }, [previews]);

  const addFiles = (selected: File[]) => {
    setError(null);
    setSuccess(null);
    const next = [...files];
    for (const file of selected) {
      if (next.length >= MAX_FILES) {
        setError(`Можно добавить не более ${MAX_FILES} изображений.`);
        break;
      }
      if (!isAcceptedImage(file)) {
        setError("Поддерживаются только изображения JPG или PNG.");
        continue;
      }
      if (file.size > MAX_FILE_SIZE) {
        setError(`Размер каждого файла должен быть не больше ${MAX_FILE_SIZE_MB} МБ.`);
        continue;
      }
      const duplicate = next.some((existing) => existing.name === file.name && existing.size === file.size);
      if (duplicate) {
        continue;
      }
      next.push(file);
    }
    setFiles(next);
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files || []);
    addFiles(selected);
    event.target.value = "";
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, idx) => idx !== index));
  };

  const handleSubmit = async () => {
    const trimmedSubject = subject.trim();
    const trimmedMessage = message.trim();
    const trimmedContact = contact.trim();
    if (!trimmedSubject || !trimmedMessage) {
      setError("Заполните тему и описание проблемы.");
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      setSending(true);
      const context = origin ? JSON.stringify({ origin }) : null;
      const response = await sendFeedback(
        trimmedSubject,
        trimmedMessage,
        files,
        context,
        feedbackType,
        trimmedContact ? trimmedContact : null,
      );
      const delivered = response.status === "sent";
      setSuccess(delivered ? "Отправлено в Telegram." : "Сохранено локально, отправим позже.");
      setSubject("");
      setMessage("");
      setFeedbackType("problem");
      setContact("");
      setFiles([]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Обратная связь</h1>
        <p className="text-muted-foreground">Опишите проблему и приложите скриншоты, если это поможет.</p>
      </header>

      {error ? <Alert variant="destructive">{error}</Alert> : null}
      {success ? <Alert variant="success">{success}</Alert> : null}

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Сообщение разработчикам</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label>Тип обращения</Label>
            <div className="ml-2 inline-flex items-center rounded-xl border bg-muted/30 p-1">
              <button
                type="button"
                onClick={() => setFeedbackType("problem")}
                aria-pressed={feedbackType === "problem"}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  feedbackType === "problem"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                Проблема
              </button>
              <button
                type="button"
                onClick={() => setFeedbackType("improvement")}
                aria-pressed={feedbackType === "improvement"}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  feedbackType === "improvement"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                Предложение по улучшению
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="feedback-subject">Тема</Label>
            <Input
              id="feedback-subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              maxLength={120}
              placeholder="Например: Ошибка при проверке пакета"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="feedback-message">Описание</Label>
            <Textarea
              id="feedback-message"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={6}
              maxLength={3500}
              placeholder="Описание проблемы. Как работает сейчас программа / как следовало бы работать программе."
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="feedback-contact">Контакт в Telegram (необязательно)</Label>
            <Input
              id="feedback-contact"
              value={contact}
              onChange={(event) => setContact(event.target.value)}
              maxLength={80}
              placeholder="Например: @username"
            />
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">
                  Скриншоты ({files.length}/{MAX_FILES})
                </div>
                <div className="text-xs text-muted-foreground">
                  До {MAX_FILES} изображений, JPG/PNG, до {MAX_FILE_SIZE_MB} МБ.
                </div>
              </div>
              <Button variant="secondary" onClick={() => fileInputRef.current?.click()} disabled={fileLimitReached}>
                Добавить изображения
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg"
                multiple
                className="hidden"
                onChange={onFileChange}
                disabled={fileLimitReached}
              />
            </div>

            {previews.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {previews.map((preview, index) => (
                  <div key={`${preview.file.name}-${preview.file.size}`} className="group relative overflow-hidden rounded-2xl border bg-muted/10">
                    <img src={preview.url} alt="" className="h-44 w-full object-cover" />
                    <button
                      type="button"
                      onClick={() => removeFile(index)}
                      className={cn(
                        "absolute right-2 top-2 rounded-full bg-background/90 px-2 py-1 text-xs font-semibold shadow-sm",
                        "opacity-0 transition-opacity group-hover:opacity-100",
                      )}
                    >
                      Удалить
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
                Скриншоты не добавлены.
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-3">
            {sending ? <Spinner /> : null}
            <Button onClick={() => void handleSubmit()} disabled={sending || !subject.trim() || !message.trim()}>
              Отправить
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default FeedbackPage;
