import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { RotateCcw, RotateCw, Trash2 } from "lucide-react";

import { FileTile } from "../components/upload/FileTile";
import { UploadIllustration } from "../components/upload/file-assets";
import { useHistoryContext } from "../contexts/history-context";
import { confirmBatchPrep, deleteDocument, fetchBatchDetails, rotateDocument } from "../lib/api";
import { cn, mapBatchStatus } from "../lib/utils";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Spinner } from "../components/ui/spinner";
import { StatusPill } from "../components/status/StatusPill";
import type { BatchDetails, DocumentPayload } from "../types/api";

type PreviewZoomProps = {
  src: string | null;
  alt: string;
};

function PreviewZoom({ src, alt }: PreviewZoomProps) {
  const [origin, setOrigin] = useState({ x: 50, y: 50 });
  const [isHovered, setIsHovered] = useState(false);

  const onMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 100;
    const y = ((event.clientY - bounds.top) / bounds.height) * 100;
    setOrigin({ x, y });
  };

  const zoomScale = isHovered ? 3 : 1;
  const sharedTransformStyle = {
    transformOrigin: `${origin.x}% ${origin.y}%`,
    transform: `scale(${zoomScale})`,
  };

  return (
    <div
      className="group relative aspect-[3/4] w-full overflow-hidden rounded-xl bg-muted"
      onMouseMove={src ? onMouseMove : undefined}
      onMouseEnter={() => {
        if (src) setIsHovered(true);
      }}
      onMouseLeave={() => {
        setIsHovered(false);
      }}
    >
      {src ? (
        <img
          src={src}
          alt={alt}
          style={sharedTransformStyle}
          className="h-full w-full object-contain transition-transform duration-200 ease-out"
        />
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Нет превью</div>
      )}
    </div>
  );
}

function resolvePreview(doc: DocumentPayload): string | null {
  const base = doc.previews?.[0] ?? null;
  if (!base) return null;
  const version = doc.updated_at ? encodeURIComponent(doc.updated_at) : "0";
  return `${base}?v=${version}`;
}

function isPdfDocument(doc: DocumentPayload): boolean {
  if (doc.mime) {
    return doc.mime.split(";", 1)[0].trim().toLowerCase() === "application/pdf";
  }
  return doc.filename.toLowerCase().endsWith(".pdf");
}

function formatElapsedTime(totalSeconds: number | null) {
  if (totalSeconds === null) {
    return "-";
  }
  const safeSeconds = Math.max(0, totalSeconds);
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function computeWeightedProgressFraction(progressPercent: number) {
  const clampedPercent = Math.max(0, Math.min(100, progressPercent));
  const firstHalfUnits = Math.min(clampedPercent, 50);
  const secondHalfUnits = Math.max(0, clampedPercent - 50);
  const secondHalfWeight = 1.5;
  const totalUnits = 50 + 50 * secondHalfWeight;
  const completedUnits = firstHalfUnits + secondHalfUnits * secondHalfWeight;
  return completedUnits / totalUnits;
}

function QueuePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { refresh } = useHistoryContext();
  const [batch, setBatch] = useState<BatchDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [prepSubmitting, setPrepSubmitting] = useState(false);
  const [actionDocId, setActionDocId] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState<number | null>(null);
  const [estimatedTotalSeconds, setEstimatedTotalSeconds] = useState<number | null>(null);
  const [lastProgressPercent, setLastProgressPercent] = useState(0);

  const batchId = searchParams.get("batch");

  const fetchBatch = useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchBatchDetails(batchId);
      setBatch(response.batch);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
      void refresh();
    }
  }, [batchId, refresh]);

  useEffect(() => {
    if (!batchId) {
      setBatch(null);
      return;
    }
    void fetchBatch();
  }, [batchId, fetchBatch]);

  useEffect(() => {
    if (!batchId || !batch || !batch.prep_complete) {
      return;
    }
    if (batch.status === "FAILED" || batch.status === "CANCELLED") {
      return;
    }
    const processingRun = batch.processing_run;
    const totalDocs = processingRun?.total ?? 0;
    const completedDocs = processingRun?.completed ?? 0;
    const totalSteps = processingRun?.steps_total ?? 0;
    const completedSteps = processingRun?.steps_completed ?? 0;
    const processingComplete = Boolean(
      processingRun && (totalSteps > 0 ? completedSteps >= totalSteps : totalDocs > 0 && completedDocs >= totalDocs),
    );
    const readyForSummary = Boolean(batch.report?.available && !batch.awaiting_processing);
    const statusComplete = ["FILLED_AUTO", "FILLED_REVIEWED", "VALIDATED", "DONE"].includes(batch.status.toUpperCase());
    if (processingComplete || readyForSummary || statusComplete) {
      navigate(`/table/${batch.id}`, { replace: true });
      return;
    }
    const interval = window.setInterval(async () => {
      try {
        const response = await fetchBatchDetails(batchId);
        setBatch(response.batch);
        const nextProcessingRun = response.batch.processing_run;
        const nextTotalDocs = nextProcessingRun?.total ?? 0;
        const nextCompletedDocs = nextProcessingRun?.completed ?? 0;
        const nextTotalSteps = nextProcessingRun?.steps_total ?? 0;
        const nextCompletedSteps = nextProcessingRun?.steps_completed ?? 0;
        const nextProcessingComplete = Boolean(
          nextProcessingRun &&
            (nextTotalSteps > 0
              ? nextCompletedSteps >= nextTotalSteps
              : nextTotalDocs > 0 && nextCompletedDocs >= nextTotalDocs),
        );
        const nextReadyForSummary = Boolean(response.batch.report?.available && !response.batch.awaiting_processing);
        const nextStatusComplete = ["FILLED_AUTO", "FILLED_REVIEWED", "VALIDATED", "DONE"].includes(
          response.batch.status.toUpperCase(),
        );
        if (nextProcessingComplete || nextReadyForSummary || nextStatusComplete) {
          window.clearInterval(interval);
          navigate(`/table/${response.batch.id}`, { replace: true });
        }
      } catch (err) {
        setError(err as Error);
      }
    }, 2000);
    return () => window.clearInterval(interval);
  }, [batch, batchId, navigate]);

  const handleRotate = useCallback(
    async (docId: string, degrees: number) => {
      if (!batchId) return;
      setActionDocId(docId);
      setError(null);
      try {
        await rotateDocument(docId, degrees);
        await fetchBatch();
      } catch (err) {
        setError(err as Error);
      } finally {
        setActionDocId(null);
      }
    },
    [batchId, fetchBatch],
  );

  const handleDelete = useCallback(
    async (docId: string) => {
      if (!batchId) return;
      setActionDocId(docId);
      setError(null);
      try {
        await deleteDocument(docId);
        await fetchBatch();
      } catch (err) {
        setError(err as Error);
      } finally {
        setActionDocId(null);
      }
    },
    [batchId, fetchBatch],
  );

  const handleConfirmPrep = useCallback(async () => {
    if (!batchId) return;
    setPrepSubmitting(true);
    setError(null);
    try {
      await confirmBatchPrep(batchId);
      await fetchBatch();
    } catch (err) {
      setError(err as Error);
    } finally {
      setPrepSubmitting(false);
    }
  }, [batchId, fetchBatch]);

  const isPrepStage = Boolean(batch && !batch.prep_complete);
  const documents = batch?.documents ?? [];
  const prepDocuments = useMemo(() => documents.filter((doc) => doc.status === "NEW"), [documents]);
  const prepList = prepDocuments.length ? prepDocuments : documents;
  const prepEmptyLabel =
    documents.length === 0 ? "Документы еще не загружены." : "Новых документов пока нет.";
  const isFailed = batch?.status === "FAILED" || batch?.status === "CANCELLED";
  const failureMessage =
    batch?.processing_warnings?.length
      ? batch.processing_warnings.join(" ")
      : "Обработка завершилась с ошибкой. Проверьте тип документа или попробуйте загрузить снова.";
  const processingRun = batch?.processing_run ?? null;
  const totalDocs = processingRun?.total ?? 0;
  const completedDocs = processingRun?.completed ?? 0;
  const totalSteps = processingRun?.steps_total ?? 0;
  const completedSteps = processingRun?.steps_completed ?? 0;
  const derivedStepsTotal = totalSteps > 0 ? totalSteps : totalDocs * 2;
  const derivedStepsCompletedRaw = totalSteps > 0 ? completedSteps : completedDocs * 2;
  const derivedStepsCompleted =
    derivedStepsTotal > 0 ? Math.min(derivedStepsTotal, Math.max(0, derivedStepsCompletedRaw)) : 0;
  const progressPercent =
    derivedStepsTotal > 0 ? Math.min(100, Math.round((derivedStepsCompleted / derivedStepsTotal) * 100)) : 0;
  const showProgress =
    Boolean(
      processingRun &&
        processingRun.mode === "initial_upload" &&
        derivedStepsTotal > 0 &&
        derivedStepsCompleted < derivedStepsTotal,
    ) && !isFailed;
  const shouldAnimateBorder = Boolean(batch && !isPrepStage);
  const showProcessingShimmer = Boolean(batch && !isPrepStage && showProgress);
  const remainingDisplaySeconds =
    elapsedSeconds !== null && estimatedTotalSeconds !== null
      ? Math.max(0, estimatedTotalSeconds - elapsedSeconds)
      : null;
  const estimateLabel = remainingDisplaySeconds !== null ? formatElapsedTime(remainingDisplaySeconds) : "ожидание";
  const processButtonLabel = remainingDisplaySeconds !== null ? `Осталось: ${estimateLabel}` : "Ожидание";

  const stepsCompletedForStages = totalSteps > 0 ? completedSteps : derivedStepsCompleted;
  const safeStepsCompleted = Math.max(0, stepsCompletedForStages);
  const ocrCompletedDocs = Math.min(totalDocs, safeStepsCompleted);
  const llmCompletedDocs = Math.min(totalDocs, Math.max(0, safeStepsCompleted - totalDocs));

  const processingStageLabel = (index: number) => {
    if (index < llmCompletedDocs) return "Обработано";
    if (index < ocrCompletedDocs) return "Распознано";
    return "В очереди";
  };

  useEffect(() => {
    if (!processingRun?.started_at) {
      setElapsedSeconds(null);
      return;
    }
    const startedAtRaw = processingRun.started_at;
    const hasTimezone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(startedAtRaw);
    const startedAt = new Date(hasTimezone ? startedAtRaw : `${startedAtRaw}Z`);
    if (Number.isNaN(startedAt.valueOf())) {
      setElapsedSeconds(null);
      return;
    }
    const updateElapsed = () => {
      const diffSeconds = Math.floor((Date.now() - startedAt.getTime()) / 1000);
      setElapsedSeconds(diffSeconds);
    };
    updateElapsed();
    const intervalId = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(intervalId);
  }, [processingRun?.started_at]);

  useEffect(() => {
    const weightedProgress = computeWeightedProgressFraction(progressPercent);
    if (elapsedSeconds === null || weightedProgress <= 0) {
      if (lastProgressPercent !== progressPercent) {
        setLastProgressPercent(progressPercent);
      }
      setEstimatedTotalSeconds(null);
      return;
    }
    if (progressPercent !== lastProgressPercent || estimatedTotalSeconds === null) {
      if (progressPercent !== lastProgressPercent) {
        setLastProgressPercent(progressPercent);
      }
      setEstimatedTotalSeconds(Math.max(elapsedSeconds, Math.round(elapsedSeconds / weightedProgress)));
    }
  }, [elapsedSeconds, estimatedTotalSeconds, lastProgressPercent, progressPercent]);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-5xl flex-col items-center justify-center gap-10">
      {batch ? (
        <div className="flex w-full items-center justify-between">
          <StatusPill status={mapBatchStatus(batch.status)} />
          <span className="text-sm text-muted-foreground">Документов: {batch.documents_count}</span>
        </div>
      ) : null}

      <div className="gradient-border w-full rounded-[26px]" style={shouldAnimateBorder ? undefined : { animation: "none" }}>
        <div
          className={cn(
            "w-full rounded-[24px] border border-transparent bg-background/95 p-8 shadow-xl",
            showProcessingShimmer && "processing-shimmer",
          )}
        >
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-6">
            {!batch ? (
              <>
                <UploadIllustration className="h-24" />
                <p className="text-sm text-muted-foreground">Выберите пакет в истории или загрузите новый.</p>
              </>
            ) : isPrepStage ? (
              <div className="w-full space-y-6">
                <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                  <div>
                    <h3 className="text-lg font-semibold">Подготовка документов</h3>
                    <p className="text-sm text-muted-foreground">
                      Проверьте страницы, удалите лишнее и поверните PDF перед запуском обработки.
                    </p>
                  </div>
                  <Button onClick={handleConfirmPrep} disabled={prepSubmitting || loading || documents.length === 0}>
                    {prepSubmitting ? "Запускаем обработку..." : "Готово"}
                  </Button>
                </div>
                {prepList.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed p-10">
                    <UploadIllustration className="h-20" />
                    <p className="text-sm text-muted-foreground">{prepEmptyLabel}</p>
                  </div>
                ) : (
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {prepList.map((doc) => {
                      const previewUrl = resolvePreview(doc);
                      const isPdf = isPdfDocument(doc);
                      const busy = actionDocId === doc.id;
                      return (
                        <div key={doc.id} className="rounded-2xl border bg-card p-4 shadow-sm">
                          <PreviewZoom src={previewUrl} alt={doc.filename} />
                          <div className="mt-3 text-sm font-medium text-foreground">{doc.filename}</div>
                          <div className="mt-3 flex items-center gap-2">
                            <Button
                              variant="secondary"
                              size="icon"
                              onClick={() => handleRotate(doc.id, -90)}
                              disabled={!isPdf || busy}
                              aria-label="Повернуть против часовой"
                            >
                              <RotateCcw className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="secondary"
                              size="icon"
                              onClick={() => handleRotate(doc.id, 90)}
                              disabled={!isPdf || busy}
                              aria-label="Повернуть по часовой"
                            >
                              <RotateCw className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="destructive"
                              size="icon"
                              onClick={() => handleDelete(doc.id)}
                              disabled={busy}
                              aria-label="Удалить документ"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                            {busy ? <Spinner className="h-4 w-4" /> : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
              <div className="w-full space-y-6">
                {documents.length === 0 ? (
                  <>
                    <UploadIllustration className="h-24" />
                    <p className="text-sm text-muted-foreground">Документы обрабатываются, ожидайте.</p>
                  </>
                ) : (
                  <div className="grid w-full gap-4 sm:grid-cols-2 md:grid-cols-3">
                    {documents.map((doc, index) => {
                      const stageLabel = processingStageLabel(index);
                      return (
                        <FileTile
                          key={doc.id}
                          item={{
                            id: doc.id,
                            name: doc.filename,
                            size: doc.pending_count,
                            meta: stageLabel,
                          }}
                          locked
                        />
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {!isPrepStage ? (
        <div className="flex w-full flex-wrap items-center gap-3">
          {showProgress ? (
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${progressPercent}%` }} />
              </div>
              <span className="text-xs text-muted-foreground tabular-nums">{progressPercent}%</span>
            </div>
          ) : (
            <div className="flex-1" />
          )}
          <div className="flex items-center gap-4 shrink-0">
            {elapsedSeconds !== null ? (
              <span className="text-sm font-medium text-muted-foreground">Прошло: {formatElapsedTime(elapsedSeconds)}</span>
            ) : null}
            <Button variant="secondary" disabled className="pointer-events-none">
              {processButtonLabel}
            </Button>
          </div>
        </div>
      ) : null}

      {isPrepStage && documents.length === 0 ? (
        <Alert variant="info">Нужно добавить хотя бы один документ перед запуском обработки.</Alert>
      ) : null}
      {isFailed ? <Alert variant="destructive">{failureMessage}</Alert> : null}
      {error ? <Alert variant="destructive">{error.message}</Alert> : null}
      {!batch && !error ? (
        <Alert variant="info">Пакет не выбран. Перейдите в историю, чтобы выбрать пакет.</Alert>
      ) : null}

    </div>
  );
}

export default QueuePage;























