import { useMemo } from "react";
import { Link } from "react-router-dom";

import { useHistoryContext } from "../contexts/history-context";
import { deriveHistoryRoute, formatShortDate, mapBatchStatus, type StatusKey } from "../lib/utils";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Spinner } from "../components/ui/spinner";
import { StatusPill } from "../components/status/StatusPill";

function HistoryPage() {
  const { batches, loading, error, refresh } = useHistoryContext();
  const grouped = useMemo(() => {
    return batches.reduce<Record<string, typeof batches>>((acc, item) => {
      const status = mapBatchStatus(item.status);
      acc[status] = acc[status] ? [...acc[status], item] : [item];
      return acc;
    }, {});
  }, [batches]);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">История</h1>
          <p className="text-muted-foreground">Полный список пакетов с возможностью перехода на соответствующий шаг.</p>
        </div>
        <Button variant="secondary" onClick={() => refresh()} disabled={loading}>
          Обновить
        </Button>
      </header>

      {loading ? (
        <div className="flex items-center gap-3 rounded-xl border border-muted bg-background px-4 py-4 text-sm text-muted-foreground">
          <Spinner />
          Загрузка истории...
        </div>
      ) : null}

      {error ? <Alert variant="destructive">{error.message}</Alert> : null}

      {!loading && batches.length === 0 ? (
        <Alert variant="info">История пуста. Загрузите новый пакет, чтобы начать.</Alert>
      ) : null}

      <div className="space-y-6">
        {Object.entries(grouped).map(([status, items]) => {
          const typedStatus = status as StatusKey;
          return (
          <Card key={status} className="rounded-3xl border bg-background/95">
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <StatusPill status={typedStatus} />
                <span>{status.toUpperCase()}</span>
              </CardTitle>
              <CardDescription>Пакетов: {items.length}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {items.map((item) => {
                const route = deriveHistoryRoute(item.id, mapBatchStatus(item.status));
                return (
                  <Link
                    key={item.id}
                    to={route}
                    className="group flex items-center justify-between gap-4 rounded-xl border border-transparent px-4 py-3 transition-colors hover:border-primary/40 hover:bg-primary/5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium" title={item.id}>
                        Пакет {item.id}
                      </p>
                      <p className="text-xs text-muted-foreground">Создан {formatShortDate(item.created_at)}</p>
                    </div>
                    <div className="text-xs text-muted-foreground">Документов: {item.documents_count}</div>
                  </Link>
                );
              })}
            </CardContent>
          </Card>
        );
        })}
      </div>
    </div>
  );
}

export default HistoryPage;
