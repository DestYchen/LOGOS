
import { useState } from "react";
import { Link } from "react-router-dom";

import { useHistoryContext } from "../contexts/history-context";
import { deriveHistoryRoute, formatShortDate, mapBatchStatus, statusLabel } from "../lib/utils";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Spinner } from "../components/ui/spinner";
import { StatusPill } from "../components/status/StatusPill";

function HistoryPage() {
  const { batches, loading, error, refresh, removeBatch } = useHistoryContext();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);

  const ordered = [...batches].sort((a, b) => {
    const dateA = a.created_at ? new Date(a.created_at).getTime() : 0;
    const dateB = b.created_at ? new Date(b.created_at).getTime() : 0;
    return dateB - dateA;
  });

  const handleDelete = async (batchId: string) => {
    if (!window.confirm("Удалить пакет и связанные данные?")) {
      return;
    }
    try {
      setDeletingId(batchId);
      await removeBatch(batchId);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">История</h1>
          <p className="text-muted-foreground">Свежие пакеты показываются сверху.</p>
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

      {!loading && ordered.length === 0 ? (
        <Alert variant="info">История пуста. Загрузите новый пакет, чтобы начать.</Alert>
      ) : null}

      <Card className="rounded-3xl border bg-background/95">
        <CardHeader>
          <CardTitle>Пакеты</CardTitle>
        </CardHeader>
        <CardContent className="divide-y">
          {ordered.map((item) => {
            const route = deriveHistoryRoute(item.id, mapBatchStatus(item.status));
            const isMenuOpen = menuId === item.id;
            return (
              <div key={item.id} className="relative flex flex-wrap items-center justify-between gap-4 py-3">
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <StatusPill status={mapBatchStatus(item.status)} />
                  <div className="min-w-0">
                    <Link to={route} className="block truncate text-sm font-medium text-primary hover:underline">
                      Пакет {item.id}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      Создан {formatShortDate(item.created_at)} · Статус: {statusLabel(mapBatchStatus(item.status))}
                    </p>
                  </div>
                </div>
                <div className="relative">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setMenuId(isMenuOpen ? null : item.id)}
                    aria-haspopup="true"
                    aria-expanded={isMenuOpen}
                  >
                    ⋯
                  </Button>
                  {isMenuOpen ? (
                    <div className="absolute right-0 z-10 mt-2 w-36 rounded-lg border bg-background p-2 shadow-lg">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="w-full justify-start text-destructive hover:text-destructive"
                        onClick={() => {
                          setMenuId(null);
                          void handleDelete(item.id);
                        }}
                        disabled={deletingId === item.id}
                      >
                        {deletingId === item.id ? "Удаление..." : "Удалить"}
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}

export default HistoryPage;
