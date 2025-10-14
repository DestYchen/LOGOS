import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import { useHistoryContext } from "../contexts/history-context";
import { fetchBatchDetails } from "../lib/api";
import { cn, formatDateTime, mapBatchStatus } from "../lib/utils";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "../components/ui/card";
import { Spinner } from "../components/ui/spinner";
import { StatusPill } from "../components/status/StatusPill";
import type { BatchDetails } from "../types/api";

function DisabledUploadCard() {
  return (
    <div className="gradient-border">
      <Card className="mx-auto max-w-3xl rounded-3xl bg-background/95 shadow-lg">
        <CardHeader className="text-center">
          <CardTitle className="text-lg">Документы в очереди</CardTitle>
          <CardDescription>Загрузка недоступна, пакет уже обрабатывается.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex min-h-[220px] flex-col items-center justify-center rounded-2xl border-2 border-dashed border-primary/40 bg-muted/40 text-muted-foreground">
            <p className="text-sm">Документы находятся в очереди на обработку.</p>
            <p className="mt-2 text-xs">Пожалуйста, дождитесь завершения обработки или перейдите к следующему шагу.</p>
          </div>
        </CardContent>
        <CardFooter className="flex items-center justify-center text-sm text-muted-foreground">
          Активация новой загрузки станет доступна после завершения текущего пакета.
        </CardFooter>
      </Card>
    </div>
  );
}

function QueuePage() {
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { refresh } = useHistoryContext();
  const [batch, setBatch] = useState<BatchDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const batchId = searchParams.get("batch");

  useEffect(() => {
    let active = true;
    if (!batchId) {
      setBatch(null);
      return () => {
        active = false;
      };
    }
    setLoading(true);
    setError(null);
    fetchBatchDetails(batchId)
      .then((response) => {
        if (active) {
          setBatch(response.batch);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err as Error);
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
          void refresh();
        }
      });
    return () => {
      active = false;
    };
  }, [batchId, refresh]);

  const documents = useMemo(() => batch?.documents ?? [], [batch]);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">В очереди</h1>
          <p className="text-muted-foreground">Текущий пакет ожидает обработки. Статус обновляется автоматически.</p>
        </div>
        {batch ? <StatusPill status={mapBatchStatus(batch.status)} /> : null}
      </header>

      <DisabledUploadCard />

      {loading ? (
        <div className="flex items-center gap-3 rounded-xl border border-muted bg-background px-4 py-4 text-sm text-muted-foreground">
          <Spinner />
          Пакет обрабатывается...
        </div>
      ) : null}

      {!batchId ? (
        <Alert variant="info">Выберите пакет из истории или загрузите новый, чтобы увидеть детали очереди.</Alert>
      ) : null}

      {error ? <Alert variant="destructive">{error.message}</Alert> : null}

      {batch ? (
        <Card className="rounded-3xl border bg-background/95">
          <CardHeader>
            <CardTitle>Пакет {batch.id.slice(0, 8)}</CardTitle>
            <CardDescription>
              Создан {formatDateTime(batch.created_at)} • Документов: {batch.documents_count}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              {documents.map((doc) => (
                <div key={doc.id} className="rounded-xl border border-muted bg-muted/20 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium" title={doc.filename}>
                        {doc.filename}
                      </p>
                      <p className="text-xs text-muted-foreground">Статус: {doc.status}</p>
                    </div>
                    <span className="text-xs text-muted-foreground">{doc.pending_count} полей</span>
                  </div>
                </div>
              ))}
            </div>
            <div className="rounded-xl border border-dashed border-primary/40 bg-primary/5 px-4 py-3 text-sm text-primary">
              Когда обработка завершится, вы автоматически перейдёте к следующему шагу.
            </div>
          </CardContent>
          <CardFooter className="flex flex-wrap items-center justify-between gap-3">
            <Button asChild variant="ghost">
              <Link to={location.state?.from ?? "/new"}>Назад</Link>
            </Button>
            <div className="space-x-2">
              <Button asChild variant="secondary" disabled={batch.awaiting_processing}>
                <Link to={`/resolve/${batch.id}`}>Документ — исправление ошибок</Link>
              </Button>
              <Button asChild variant="default" disabled={!batch.can_complete}>
                <Link to={`/table/${batch.id}`}>Итоговая таблица</Link>
              </Button>
            </div>
          </CardFooter>
        </Card>
      ) : null}
    </div>
  );
}

export default QueuePage;
