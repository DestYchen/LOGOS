
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { FileTile, type FileEntry } from "../components/upload/FileTile";
import { UploadIllustration } from "../components/upload/file-assets";
import { useHistoryContext } from "../contexts/history-context";
import { fetchBatchDetails } from "../lib/api";
import { cn, mapBatchStatus, statusLabel } from "../lib/utils";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Spinner } from "../components/ui/spinner";
import { StatusPill } from "../components/status/StatusPill";
import type { BatchDetails } from "../types/api";

function QueuePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { refresh } = useHistoryContext();
  const [batch, setBatch] = useState<BatchDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const batchId = searchParams.get("batch");

  const files: FileEntry[] = useMemo(() => {
    if (!batch) return [];
    return batch.documents.map((doc) => ({
      id: doc.id,
      name: doc.filename,
      size: doc.pending_count,
      meta: statusLabel(mapBatchStatus(doc.status)),
    }));
  }, [batch]);

  useEffect(() => {
    let cancelled = false;
    if (!batchId) {
      setBatch(null);
      return () => {
        cancelled = true;
      };
    }
    setLoading(true);
    setError(null);
    fetchBatchDetails(batchId)
      .then((response) => {
        if (!cancelled) {
          setBatch(response.batch);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err as Error);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          void refresh();
        }
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, refresh]);

  useEffect(() => {
    if (!batchId) return;
    if (!batch) return;
    if (!batch.awaiting_processing && batch.pending_total === 0) {
      navigate(`/resolve/${batch.id}`, { replace: true });
      return;
    }
    const interval = window.setInterval(async () => {
      try {
        const response = await fetchBatchDetails(batchId);
        setBatch(response.batch);
        if (!response.batch.awaiting_processing && response.batch.pending_total === 0) {
          window.clearInterval(interval);
          navigate(`/resolve/${response.batch.id}`, { replace: true });
        }
      } catch (err) {
        setError(err as Error);
      }
    }, 2000);
    return () => window.clearInterval(interval);
  }, [batch, batchId, navigate]);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-4xl flex-col items-center justify-center gap-10">
      {batch ? (
        <div className="flex w-full items-center justify-between">
          <StatusPill status={mapBatchStatus(batch.status)} />
          <span className="text-sm text-muted-foreground">Документов: {batch.documents_count}</span>
        </div>
      ) : null}

      <div className="gradient-border w-full rounded-[26px]">
        <div className={cn("w-full rounded-[24px] border border-transparent bg-background/95 p-8 shadow-xl")}>
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-6">
            {!batch ? (
              <>
                <UploadIllustration className="h-24" />
                <p className="text-sm text-muted-foreground">
                  Выберите пакет из истории, чтобы отследить его очередь обработки.
                </p>
              </>
            ) : files.length === 0 ? (
              <>
                <UploadIllustration className="h-24" />
                <p className="text-sm text-muted-foreground">Документы пакета появятся здесь после загрузки.</p>
              </>
            ) : (
              <div className="grid w-full gap-4 sm:grid-cols-2 md:grid-cols-3">
                {files.map((item) => (
                  <FileTile key={item.id} item={item} locked />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        {loading || (batch && batch.awaiting_processing) ? <Spinner /> : null}
        <Button variant="secondary" disabled className="pointer-events-none">
          Обработка
        </Button>
      </div>

      {error ? <Alert variant="destructive">{error.message}</Alert> : null}
      {!batch && !error ? (
        <Alert variant="info">Загрузите или выберите пакет, чтобы увидеть его состояние очереди.</Alert>
      ) : null}
    </div>
  );
}

export default QueuePage;
