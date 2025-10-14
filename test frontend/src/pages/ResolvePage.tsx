import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Spinner } from "../components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Textarea } from "../components/ui/textarea";
import { StatusPill } from "../components/status/StatusPill";
import { useHistoryContext } from "../contexts/history-context";
import {
  completeBatch,
  confirmField,
  deleteDocument,
  fetchBatchDetails,
  refillDocument,
  setDocumentType,
  updateField,
} from "../lib/api";
import { cn, formatDateTime, mapBatchStatus } from "../lib/utils";
import type { BatchDetails, DocumentPayload, FieldState } from "../types/api";

type DraftState = Record<string, string>;

function usePendingActions() {
  const [pendingMap, setPendingMap] = useState<Record<string, boolean>>({});

  const setPending = useCallback((key: string, value: boolean) => {
    setPendingMap((prev) => {
      if (prev[key] === value) return prev;
      const next = { ...prev };
      if (value) {
        next[key] = true;
      } else {
        delete next[key];
      }
      return next;
    });
  }, []);

  const isPending = useCallback((key: string) => Boolean(pendingMap[key]), [pendingMap]);

  return { setPending, isPending };
}

function groupFields(document: DocumentPayload) {
  const required = document.fields.filter((field) => field.reason === "missing");
  const lowConfidence = document.fields.filter((field) => field.reason === "low_confidence");
  const other = document.fields.filter((field) => field.reason !== "missing" && field.reason !== "low_confidence");
  return { required, lowConfidence, other };
}

function DocumentViewer({ previews, highlight }: { previews: string[]; highlight: boolean }) {
  const [origin, setOrigin] = useState({ x: 50, y: 50 });

  const onMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 100;
    const y = ((event.clientY - bounds.top) / bounds.height) * 100;
    setOrigin({ x, y });
  };

  const primaryPreview = previews[0];

  return (
    <div
      className={cn(
        "relative aspect-[3/4] max-h-[640px] overflow-hidden rounded-3xl border bg-background shadow-lg",
        highlight && "ring-4 ring-primary/50",
      )}
      onMouseMove={onMouseMove}
    >
      {primaryPreview ? (
        <img
          src={primaryPreview}
          alt="Просмотр документа"
          style={{ transformOrigin: `${origin.x}% ${origin.y}%` }}
          className="h-full w-full object-contain transition-transform duration-200 ease-out hover:scale-[2]"
        />
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Превью документа отсутствует
        </div>
      )}
    </div>
  );
}

function ResolvePage() {
  const params = useParams();
  const navigate = useNavigate();
  const { refresh } = useHistoryContext();
  const { setPending, isPending } = usePendingActions();

  const batchId = params.batchId;
  const docIndexParam = params.docIndex ? Number.parseInt(params.docIndex, 10) : 0;

  const [batch, setBatch] = useState<BatchDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [drafts, setDrafts] = useState<DraftState>({});
  const [highlightedField, setHighlightedField] = useState<string | null>(null);
  const [showAllFields, setShowAllFields] = useState(false);

  useEffect(() => {
    if (!batchId) return;
    let active = true;
    setLoading(true);
    setError(null);
    fetchBatchDetails(batchId)
      .then((response) => {
        if (!active) return;
        setBatch(response.batch);
        const index = Number.isFinite(docIndexParam) && docIndexParam >= 0 ? docIndexParam : 0;
        setActiveIndex(Math.min(index, response.batch.documents.length - 1));
        const initialDrafts: DraftState = {};
        response.batch.documents.forEach((doc) => {
          doc.fields.forEach((field) => {
            initialDrafts[`${doc.id}:${field.field_key}`] = field.value ?? "";
          });
        });
        setDrafts(initialDrafts);
        setHighlightedField(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err as Error);
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
        void refresh();
      });
    return () => {
      active = false;
    };
  }, [batchId, docIndexParam, refresh]);

  const documents = batch?.documents ?? [];
  const currentDoc = documents[activeIndex];

  const grouped = useMemo(() => {
    if (!currentDoc) return { required: [], lowConfidence: [], other: [] };
    return groupFields(currentDoc);
  }, [currentDoc]);

  const handleRefresh = useCallback(async () => {
    if (!batchId) return;
    setPending("reload", true);
    try {
      const response = await fetchBatchDetails(batchId);
      setBatch(response.batch);
      const nextDrafts: DraftState = {};
      response.batch.documents.forEach((doc) => {
        doc.fields.forEach((field) => {
          nextDrafts[`${doc.id}:${field.field_key}`] = field.value ?? "";
        });
      });
      setDrafts(nextDrafts);
      setHighlightedField(null);
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setPending("reload", false);
      void refresh();
    }
  }, [batchId, refresh, setPending]);

  const withAction = useCallback(
    async (key: string, fn: () => Promise<void>) => {
      setActionError(null);
      setMessage(null);
      setPending(key, true);
      try {
        await fn();
        await handleRefresh();
      } catch (err) {
        setActionError((err as Error).message);
      } finally {
        setPending(key, false);
      }
    },
    [handleRefresh, setPending],
  );

  const handleDocTypeChange = async (doc: DocumentPayload, docType: string) => {
    await withAction(`doc:${doc.id}:type`, async () => {
      await setDocumentType(doc.id, docType);
      setMessage("Тип документа сохранён");
    });
  };

  const handleRefill = async (doc: DocumentPayload) => {
    await withAction(`doc:${doc.id}:refill`, async () => {
      await refillDocument(doc.id);
      setMessage("Документ перерасчитан");
    });
  };

  const handleDelete = async (doc: DocumentPayload) => {
    await withAction(`doc:${doc.id}:delete`, async () => {
      await deleteDocument(doc.id);
      setMessage("Документ удалён");
      if (documents.length > 1) {
        const nextIndex = Math.max(0, Math.min(activeIndex, documents.length - 2));
        setActiveIndex(nextIndex);
        setHighlightedField(null);
      }
    });
  };

  const handleSaveField = async (doc: DocumentPayload, field: FieldState) => {
    const value = drafts[`${doc.id}:${field.field_key}`]?.trim() ?? "";
    await withAction(`field:${doc.id}:${field.field_key}:save`, async () => {
      await updateField(doc.id, field.field_key, value === "" ? null : value);
      setMessage("Поле сохранено");
    });
  };

  const handleConfirmField = async (doc: DocumentPayload, field: FieldState) => {
    await withAction(`field:${doc.id}:${field.field_key}:confirm`, async () => {
      await confirmField(doc.id, field.field_key);
      setMessage("Поле подтверждено");
    });
  };

  const handleComplete = async () => {
    if (!batch) return;
    await withAction(`batch:${batch.id}:complete`, async () => {
      await completeBatch(batch.id);
      setMessage("Пакет отправлен на проверку");
      navigate(`/table/${batch.id}`);
    });
  };

  const handleContinue = () => {
    if (!batch) return;
    if (activeIndex < documents.length - 1) {
      const nextIndex = activeIndex + 1;
      setActiveIndex(nextIndex);
      setHighlightedField(null);
      navigate(`/resolve/${batch.id}/${nextIndex}`, { replace: true });
    }
  };

  if (!batchId) {
    return <Alert variant="destructive">Не указан идентификатор пакета.</Alert>;
  }

  if (loading) {
    return (
      <div className="flex h-80 items-center justify-center text-muted-foreground">
        <Spinner className="mr-3" /> Загрузка пакета {batchId}...
      </div>
    );
  }

  if (error || !batch) {
    return <Alert variant="destructive">{error ? error.message : "Пакет не найден"}</Alert>;
  }

  if (!currentDoc) {
    return <Alert variant="info">В пакете нет документов. Вернитесь к истории и выберите другой пакет.</Alert>;
  }

  const totalDocs = documents.length;
  const docDraft = (fieldKey: string) => drafts[`${currentDoc.id}:${fieldKey}`] ?? "";

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Документ — исправление ошибок</h1>
          <p className="text-muted-foreground">
            Пакет {batch.id.slice(0, 8)} • Создан {formatDateTime(batch.created_at)} • Статус пакета:
            <span className="ml-2">
              <StatusPill status={mapBatchStatus(batch.status)} />
            </span>
          </p>
        </div>
        <Button variant="secondary" onClick={() => handleRefresh()} disabled={isPending("reload")}>Обновить</Button>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">Документ {activeIndex + 1} из {totalDocs}</span>
        <div className="flex items-center gap-2">
          {documents.map((doc, index) => (
            <button
              key={doc.id}
              type="button"
              onClick={() => {
                setActiveIndex(index);
                navigate(`/resolve/${batch.id}/${index}`, { replace: true });
              }}
              className={cn(
                "h-3 w-3 rounded-full transition-colors",
                index === activeIndex ? "bg-primary" : "bg-muted-foreground/40 hover:bg-primary/60",
              )}
              aria-label={`Документ ${index + 1}`}
            />
          ))}
        </div>
      </div>

      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)] xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card className="rounded-3xl border bg-background/90">
            <CardHeader>
              <CardTitle>{currentDoc.filename}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Тип документа</Label>
                <Select
                  defaultValue={currentDoc.doc_type}
                  onValueChange={(value) => void handleDocTypeChange(currentDoc, value)}
                  disabled={isPending(`doc:${currentDoc.id}:type`)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Выберите тип" />
                  </SelectTrigger>
                  <SelectContent>
                    {batch.doc_types.map((docType) => (
                      <SelectItem key={docType} value={docType}>
                        {docType}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => void handleDelete(currentDoc)}
                  disabled={isPending(`doc:${currentDoc.id}:delete`)}
                >
                  Удалить документ
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void handleRefill(currentDoc)}
                  disabled={isPending(`doc:${currentDoc.id}:refill`)}
                >
                  Сохранить и пересчитать
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-3xl border bg-background/90">
            <CardHeader>
              <CardTitle>Ошибки и проверки</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <section className="space-y-3">
                <h3 className="text-sm font-medium">Обязательные поля</h3>
                <div className="space-y-3">
                  {grouped.required.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Все обязательные поля заполнены.</p>
                  ) : (
                    grouped.required.map((field) => (
                      <div key={field.field_key} className="rounded-xl border border-amber-400/40 bg-amber-500/10 px-4 py-3">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium">{field.field_key}</p>
                            <p className="text-xs text-muted-foreground">Требуется заполнить поле</p>
                          </div>
                          <Badge variant="warning">Обязательно</Badge>
                        </div>
                        <Input
                          className="mt-3"
                          value={docDraft(field.field_key)}
                          onChange={(event) =>
                            setDrafts((prev) => ({ ...prev, [`${currentDoc.id}:${field.field_key}`]: event.target.value }))
                          }
                        />
                        <div className="mt-3 flex flex-wrap items-center gap-3">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => void handleSaveField(currentDoc, field)}
                            disabled={isPending(`field:${currentDoc.id}:${field.field_key}:save`)}
                          >
                            Сохранить и продолжить
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setHighlightedField(field.field_key)}
                          >
                            Показать на документе
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className="space-y-3">
                <h3 className="text-sm font-medium">Поля с низкой уверенностью</h3>
                <div className="space-y-3">
                  {grouped.lowConfidence.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Нет полей с низкой уверенностью.</p>
                  ) : (
                    grouped.lowConfidence.map((field) => (
                      <div key={field.field_key} className="rounded-xl border border-primary/40 bg-primary/5 px-4 py-3">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-sm font-medium">{field.field_key}</p>
                            <p className="text-xs text-muted-foreground">
                              Текущая уверенность: {field.confidence_display ?? "—"}
                            </p>
                          </div>
                          <Button size="sm" variant="ghost" onClick={() => setHighlightedField(field.field_key)}>
                            Показать на документе
                          </Button>
                        </div>
                        <Textarea
                          className="mt-3"
                          value={docDraft(field.field_key)}
                          onChange={(event) =>
                            setDrafts((prev) => ({ ...prev, [`${currentDoc.id}:${field.field_key}`]: event.target.value }))
                          }
                          rows={3}
                        />
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => void handleSaveField(currentDoc, field)}
                            disabled={isPending(`field:${currentDoc.id}:${field.field_key}:save`)}
                          >
                            Изменить
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void handleConfirmField(currentDoc, field)}
                            disabled={isPending(`field:${currentDoc.id}:${field.field_key}:confirm`)}
                          >
                            Подтвердить
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className="space-y-3">
                <Button variant="ghost" size="sm" onClick={() => setShowAllFields((prev) => !prev)}>
                  {showAllFields ? "Скрыть все поля" : "Показать все поля"}
                </Button>
                {showAllFields ? (
                  <div className="space-y-2 rounded-xl border border-muted bg-muted/20 p-3">
                    {grouped.other.map((field) => (
                      <div key={field.field_key} className="rounded-lg bg-background px-3 py-2 text-sm">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{field.field_key}</span>
                          <span className="text-xs text-muted-foreground">{field.reason}</span>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">{field.value ?? "—"}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
              </section>
            </CardContent>
            <CardFooter className="flex flex-wrap items-center justify-between gap-3">
              <Button variant="ghost" asChild>
                <Link to="/history">История</Link>
              </Button>
              <Button variant="default" onClick={handleContinue} disabled={activeIndex >= totalDocs - 1}>
                Сохранить и продолжить
              </Button>
            </CardFooter>
          </Card>
        </div>

        <div className="space-y-6">
          <DocumentViewer previews={currentDoc.previews} highlight={Boolean(highlightedField)} />

          <Tabs defaultValue="json" className="rounded-3xl border bg-background/90">
            <Card>
              <CardHeader>
                <CardTitle>Дополнительные данные</CardTitle>
              </CardHeader>
              <CardContent>
                <TabsList>
                  <TabsTrigger value="json">JSON</TabsTrigger>
                  <TabsTrigger value="products">Товары</TabsTrigger>
                </TabsList>
                <TabsContent value="json" className="mt-4">
                  {currentDoc.filled_json ? (
                    <pre className="max-h-[320px] overflow-auto rounded-xl bg-muted/30 p-4 text-xs">
                      {currentDoc.filled_json}
                    </pre>
                  ) : (
                    <p className="text-sm text-muted-foreground">JSON появится после завершения обработки.</p>
                  )}
                </TabsContent>
                <TabsContent value="products" className="mt-4">
                  {currentDoc.products.rows.length ? (
                    <div className="overflow-auto rounded-xl border">
                      <table className="w-full text-sm">
                        <thead className="bg-muted/40">
                          <tr>
                            {currentDoc.products.columns.map((column) => (
                              <th key={column.key} className="px-3 py-2 text-left font-medium">
                                {column.label}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {currentDoc.products.rows.map((row) => (
                            <tr key={row.key} className="border-t">
                              {currentDoc.products.columns.map((column) => {
                                const cell = row.cells[column.key];
                                return (
                                  <td key={column.key} className="px-3 py-2 text-sm">
                                    <div>{cell?.value ?? "—"}</div>
                                    {cell?.confidence_display ? (
                                      <div className="text-xs text-muted-foreground">
                                        {cell.confidence_display}
                                      </div>
                                    ) : null}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">Товарных позиций нет.</p>
                  )}
                </TabsContent>
              </CardContent>
            </Card>
          </Tabs>
        </div>
      </div>

      <Card className="rounded-3xl border bg-background/90">
        <CardHeader>
          <CardTitle>Завершение</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            Проверьте, что все документы обработаны и обязательные поля заполнены. После отправки пакет перейдёт на этап
            итоговой таблицы.
          </p>
        </CardContent>
        <CardFooter className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="secondary" asChild>
            <Link to={`/table/${batch.id}`}>Открыть итоговую таблицу</Link>
          </Button>
          <Button onClick={() => void handleComplete()} disabled={isPending(`batch:${batch.id}:complete`)}>
            Отправить на проверку
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

export default ResolvePage;
