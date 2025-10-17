
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Spinner } from "../components/ui/spinner";
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

type HighlightState = {
  fieldKey: string;
  bbox?: number[] | null;
  page?: number | null;
};
type OverlayBox = HighlightRegion & {
  fieldKey: string;
};

type OverlayRenderItem = {
  key: string;
  style: CSSProperties;
  color: string;
  thickness: number;
};

const CALIBRATION: CalibrationState = {
  scaleX: 0.41,
  scaleY: 0.41,
  offsetX: 8,
  offsetY: 0,
};


const REFRESH_DELAY_MS = 2000;

function usePendingMap() {
  const [state, setState] = useState<Record<string, boolean>>({});
  const set = useCallback((key: string, value: boolean) => {
    setState((prev) => {
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
  const isPending = useCallback((key: string) => Boolean(state[key]), [state]);
  return { setPending: set, isPending };
}

type HighlightRegion = {
  fieldKey?: string;
  bbox?: number[] | null;
  page?: number | null;
};

type CalibrationState = {
  scaleX: number;
  scaleY: number;
  offsetX: number;
  offsetY: number;
};

function DocumentViewer({
  previews,
  highlight,
  boxes,
  showBoxes,
}: {
  previews: string[];
  highlight: HighlightRegion | null;
  boxes: OverlayBox[];
  showBoxes: boolean;
}) {
  const [origin, setOrigin] = useState({ x: 50, y: 50 });
  const [dims, setDims] = useState({ naturalWidth: 0, naturalHeight: 0, width: 0, height: 0 });
  const [isHovered, setIsHovered] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const calibration = CALIBRATION;

  const imageIndex = highlight?.page && highlight.page > 0 ? Math.min(highlight.page - 1, previews.length - 1) : 0;
  const currentPage = imageIndex + 1;
  const src = previews[imageIndex] ?? previews[0];

  const updateSizes = useCallback(() => {
    if (!imgRef.current) return;
    const { naturalWidth, naturalHeight, clientWidth, clientHeight } = imgRef.current;
    setDims({ naturalWidth, naturalHeight, width: clientWidth, height: clientHeight });
  }, []);

  const onMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 100;
    const y = ((event.clientY - bounds.top) / bounds.height) * 100;
    setOrigin({ x, y });
  };

  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !imgRef.current) return;
    const observer = new ResizeObserver(() => updateSizes());
    observer.observe(imgRef.current);
    return () => observer.disconnect();
  }, [updateSizes, src]);

  const createOverlay = useCallback(
    (fieldKey: string, bbox?: number[] | null, color = "hsl(var(--primary) / 0.45)", thickness = 3): OverlayRenderItem | null => {
      if (!bbox || bbox.length !== 4 || dims.naturalWidth === 0 || dims.naturalHeight === 0) return null;
      const [x1, y1, x2, y2] = bbox;
      const baseScaleX = dims.width / dims.naturalWidth;
      const baseScaleY = dims.height / dims.naturalHeight;
      const adjustedScaleX = baseScaleX * calibration.scaleX;
      const adjustedScaleY = baseScaleY * calibration.scaleY;
      const width = Math.max((x2 - x1) * adjustedScaleX, 1.5);
      const height = Math.max((y2 - y1) * adjustedScaleY, 1.5);
      const left = x1 * adjustedScaleX + calibration.offsetX;
      const top = y1 * adjustedScaleY + calibration.offsetY;
      return {
        key: fieldKey,
        style: {
          left: `${left - 10}px`,
          top: `${top - 10}px`,
          width: `${width + 20}px`,
          height: `${height + 20}px`,
        },
        color,
        thickness,
      };
    },
    [dims, calibration],
  );

  const baseOverlays = useMemo(() => {
    if (!boxes.length) return [] as OverlayRenderItem[];
    return boxes
      .filter((box) => (box.page && box.page > 0 ? box.page : 1) === currentPage)
      .map((box) => createOverlay(box.fieldKey, box.bbox ?? null))
      .filter((item): item is OverlayRenderItem => Boolean(item));
  }, [boxes, currentPage, createOverlay]);

  const highlightOverlay = useMemo(() => {
    if (!highlight) return null;
    const pageNumber = highlight.page && highlight.page > 0 ? highlight.page : 1;
    if (pageNumber !== currentPage) return null;
    return createOverlay(highlight.fieldKey ?? "highlight", highlight.bbox ?? null, "hsl(var(--primary))", 4);
  }, [highlight, currentPage, createOverlay]);

  const overlaysToRender = useMemo(() => {
    const items: OverlayRenderItem[] = [];
    if (showBoxes) {
      items.push(...baseOverlays.filter((item) => item.key !== highlightOverlay?.key));
    }
    if (highlightOverlay) {
      items.push(highlightOverlay);
    }
    return items;
  }, [showBoxes, baseOverlays, highlightOverlay]);

  const zoomScale = isHovered ? 3 : 1;
  const transformOriginValue = `${origin.x}% ${origin.y}%`;
  const sharedTransformStyle = {
    transformOrigin: transformOriginValue,
    transform: `scale(${zoomScale})`,
  };

  const highlightCoversDocument = Boolean(highlight) && (!highlight?.bbox || highlight.bbox.length !== 4);

  const renderOverlay = (overlay: OverlayRenderItem) => (
    <div
      key={overlay.key}
      className="pointer-events-none absolute"
      style={{
        ...overlay.style,
        border: `${overlay.thickness}px solid ${overlay.color}`,
        boxShadow: "0 0 8px rgba(0,0,0,0.2)",
      }}
    />
  );

  return (
    <div className="space-y-4">
      <div
        className={cn(
          "group relative aspect-[3/4] max-h-[640px] overflow-hidden rounded-3xl border bg-background shadow-lg transition-colors",
          highlightCoversDocument ? "border-4 border-primary/70" : "",
        )}
        onMouseMove={onMouseMove}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {src ? (
          <>
            <img
              ref={imgRef}
              src={src}
              alt=" "
              onLoad={updateSizes}
              style={sharedTransformStyle}
              className="h-full w-full object-contain transition-transform duration-200 ease-out"
            />
            <div className="pointer-events-none absolute inset-0" style={sharedTransformStyle}>
              {overlaysToRender.map(renderOverlay)}
            </div>
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              
          </div>
        )}
      </div>
    </div>
  );
}
function ResolvePage() {
  const params = useParams();
  const navigate = useNavigate();
  const { refresh } = useHistoryContext();
  const { setPending, isPending } = usePendingMap();

  const batchId = params.batchId;
  const initialIndex = params.docIndex ? Number.parseInt(params.docIndex, 10) : 0;

  const [batch, setBatch] = useState<BatchDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [drafts, setDrafts] = useState<DraftState>({});
  const [highlightedField, setHighlightedField] = useState<HighlightState | null>(null);
  const [showBoxes, setShowBoxes] = useState(false);

  const fetchAndSelect = useCallback(
    async (targetIndex?: number) => {
      if (!batchId) return;
      const response = await fetchBatchDetails(batchId);
      setBatch(response.batch);
      const nextIndex = targetIndex ?? activeIndex;
      setActiveIndex(Math.min(Math.max(nextIndex, 0), Math.max(response.batch.documents.length - 1, 0)));
      const nextDrafts: DraftState = {};
      response.batch.documents.forEach((doc) => {
        doc.fields.forEach((field) => {
          nextDrafts[`${doc.id}:${field.field_key}`] = field.value ?? "";
        });
      });
      setDrafts(nextDrafts);
      setHighlightedField(null);
      void refresh();
    },
    [activeIndex, batchId, refresh],
  );

  useEffect(() => {
    let cancelled = false;
    if (!batchId) {
      setError(new Error("Не указан идентификатор пакета"));
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchAndSelect(initialIndex)
      .catch((err) => {
        if (!cancelled) {
          setError(err as Error);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, fetchAndSelect, initialIndex]);

  const documents = batch?.documents ?? [];
  const currentDoc = documents[activeIndex];
  const overlayBoxes = useMemo<OverlayBox[]>(() => {
    if (!currentDoc) return [];
    return currentDoc.fields.map((field) => ({
      fieldKey: field.field_key,
      bbox: Array.isArray(field.bbox) ? field.bbox : null,
      page: field.page ?? null,
    }));
  }, [currentDoc]);

  useEffect(() => {
    setShowBoxes(false);
  }, [activeIndex]);

  const grouped = useMemo(() => {
    if (!currentDoc) {
      return { required: [] as FieldState[], lowConfidence: [] as FieldState[], other: [] as FieldState[] };
    }
    const required = currentDoc.fields.filter((field) => field.reason === "missing");
    const lowConfidence = currentDoc.fields.filter((field) => field.reason === "low_confidence");
    const other = currentDoc.fields.filter(
      (field) => field.reason !== "missing" && field.reason !== "low_confidence",
    );
    return { required, lowConfidence, other };
  }, [currentDoc]);

  const updateDraft = (docId: string, fieldKey: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [`${docId}:${fieldKey}`]: value }));
  };

  const draftValue = (docId: string, fieldKey: string) => drafts[`${docId}:${fieldKey}`] ?? "";

  const waitForDocument = useCallback(
    async (docId: string) => {
      if (!batchId) return;
      const maxAttempts = 5;
      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        const response = await fetchBatchDetails(batchId);
        const doc = response.batch.documents.find((item) => item.id === docId);
        if (doc && !doc.processing) {
          setBatch(response.batch);
          const nextDrafts: DraftState = {};
          response.batch.documents.forEach((item) => {
            item.fields.forEach((field) => {
              nextDrafts[`${item.id}:${field.field_key}`] = field.value ?? "";
            });
          });
          setDrafts(nextDrafts);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, REFRESH_DELAY_MS));
      }
      await fetchAndSelect(activeIndex);
    },
    [activeIndex, batchId, fetchAndSelect],
  );

  const withAction = useCallback(
    async (key: string, action: () => Promise<void>) => {
      setActionError(null);
      setMessage(null);
      setPending(key, true);
      try {
        await action();
      } catch (err) {
        setActionError((err as Error).message);
      } finally {
        setPending(key, false);
      }
    },
    [setPending],
  );

  const handleSetType = async (doc: DocumentPayload, docType: string) => {
    await withAction(`doc:${doc.id}:type`, async () => {
      await setDocumentType(doc.id, docType);
      await waitForDocument(doc.id);
      setMessage("Тип документа сохранён");
    });
  };

  const handleRefill = async (doc: DocumentPayload) => {
    await withAction(`doc:${doc.id}:refill`, async () => {
      await refillDocument(doc.id);
      await waitForDocument(doc.id);
      setMessage("Документ перерасчитан");
    });
  };

  const handleDelete = async (doc: DocumentPayload) => {
    if (!window.confirm("Удалить документ из пакета?")) {
      return;
    }
    await withAction(`doc:${doc.id}:delete`, async () => {
      await deleteDocument(doc.id);
      await fetchAndSelect(Math.max(activeIndex - 1, 0));
      setMessage("Документ удалён");
    });
  };

  const handleSaveField = async (doc: DocumentPayload, field: FieldState) => {
    const value = draftValue(doc.id, field.field_key).trim();
    await withAction(`field:${doc.id}:${field.field_key}:save`, async () => {
      await updateField(doc.id, field.field_key, value === "" ? null : value);
      await fetchAndSelect(activeIndex);
      setMessage("Поле сохранено");
    });
  };

  const handleConfirmField = async (doc: DocumentPayload, field: FieldState) => {
    await withAction(`field:${doc.id}:${field.field_key}:confirm`, async () => {
      await confirmField(doc.id, field.field_key);
      await fetchAndSelect(activeIndex);
      setMessage("Поле подтверждено");
    });
  };

  const handleComplete = async () => {
    if (!batch) return;
    await withAction(`batch:${batch.id}:complete`, async () => {
      await completeBatch(batch.id);
      setMessage("Пакет отправлен на проверку");
      setTimeout(() => navigate(`/table/${batch.id}`), 1000);
    });
  };

  const goToDocument = (index: number) => {
    setHighlightedField(null);
    setActiveIndex(index);
    navigate(`/resolve/${batchId}/${index}`, { replace: true });
  };

  if (!batchId) {
    return <Alert variant="destructive">Не указан идентификатор пакета.</Alert>;
  }

  if (loading) {
    return (
      <div className="flex h-80 items-center justify-center text-muted-foreground">
        <Spinner className="mr-3" /> Загрузка пакета...
      </div>
    );
  }

  if (error) {
    return <Alert variant="destructive">{error.message}</Alert>;
  }

  if (!batch || !currentDoc) {
    return <Alert variant="info">Документы недоступны для обработки.</Alert>;
  }

  const totalDocs = documents.length;
  const isLastDocument = totalDocs > 0 && activeIndex === totalDocs - 1;
  const canSubmit = batch.pending_total === 0 && !batch.awaiting_processing;

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Документ — исправление ошибок</h1>
        <p className="text-muted-foreground">Пакет {batch.id.slice(0, 8)} · Статус пакета:</p>
        <div className="mt-1">
          <StatusPill status={mapBatchStatus(batch.status)} />
        </div>
        <p className="text-sm text-muted-foreground">Создан {formatDateTime(batch.created_at)} · Документов: {totalDocs}</p>
      </header>

      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">
          Документ {activeIndex + 1} из {totalDocs}
        </span>
        <div className="flex items-center gap-2">
          {documents.map((doc, index) => (
            <button
              key={doc.id}
              type="button"
              onClick={() => goToDocument(index)}
              className={cn(
                "h-3 w-3 rounded-full transition-colors",
                index === activeIndex ? "bg-primary" : "bg-muted-foreground/40 hover:bg-primary/60",
              )}
              aria-label={`Документ ${index + 1}`}
            />
          ))}
        </div>
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card className="rounded-3xl border bg-background">
            <CardHeader>
              <CardTitle className="text-lg">{currentDoc.filename}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>Тип документа</Label>
                <Select
                  value={currentDoc.doc_type}
                  onValueChange={(value) => void handleSetType(currentDoc, value)}
                  disabled={isPending(`doc:${currentDoc.id}:type`)}
                >
                  <SelectTrigger className="mt-1">
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

          <Card className="rounded-3xl border bg-background">
            <CardHeader>
              <CardTitle className="text-lg">Проблемы для исправления</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <section className="space-y-3">
                <h2 className="text-sm font-semibold">Обязательные поля</h2>
                {grouped.required.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Все обязательные поля заполнены.</p>
                ) : (
                  grouped.required.map((field) => (
                    <div key={field.field_key} className="rounded-xl border border-amber-400/40 bg-amber-500/10 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium">{field.field_key}</p>
                          <p className="text-xs text-muted-foreground">Требуется заполнить поле</p>
                        </div>
                        <Badge variant="warning">Обязательно</Badge>
                      </div>
                      <Input
                        className="mt-3"
                        value={draftValue(currentDoc.id, field.field_key)}
                        onChange={(event) => updateDraft(currentDoc.id, field.field_key, event.target.value)}
                      />
                      <div className="mt-3 flex flex-wrap items-center gap-2">
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
                          onClick={() => setHighlightedField({ fieldKey: field.field_key, bbox: field.bbox ?? null, page: field.page ?? null })}
                        >
                          Показать на документе
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </section>

              <section className="space-y-3">
                <h2 className="text-sm font-semibold">Поля с низкой уверенностью</h2>
                {grouped.lowConfidence.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Нет полей с низкой уверенностью.</p>
                ) : (
                  grouped.lowConfidence.map((field) => (
                    <div key={field.field_key} className="rounded-xl border border-primary/30 bg-primary/5 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium">{field.field_key}</p>
                          <p className="text-xs text-muted-foreground">
                            Уверенность: {field.confidence_display ?? "—"}
                          </p>
                        </div>
                        <Button size="sm" variant="ghost" onClick={() => setHighlightedField({ fieldKey: field.field_key, bbox: field.bbox ?? null, page: field.page ?? null })}>
                          Показать на документе
                        </Button>
                      </div>
                      <Textarea
                        className="mt-3"
                        rows={3}
                        value={draftValue(currentDoc.id, field.field_key)}
                        onChange={(event) => updateDraft(currentDoc.id, field.field_key, event.target.value)}
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
              </section>

              {grouped.other.length ? (
                <section className="space-y-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setHighlightedField(null)}
                    className="text-sm"
                  >
                    Снять подсветку
                  </Button>
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
                </section>
              ) : null}
            </CardContent>

            <CardFooter className="flex flex-wrap items-center justify-end gap-3">
              {activeIndex < totalDocs - 1 ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (activeIndex < totalDocs - 1) {
                      goToDocument(activeIndex + 1);
                    }
                  }}
                >
                  Следующий документ
                </Button>
              ) : null}
            </CardFooter>
          </Card>
        </div>

        <div className="space-y-6">
          <div className="space-y-3">
            <DocumentViewer previews={currentDoc.previews} highlight={highlightedField} boxes={overlayBoxes} showBoxes={showBoxes} />
            <div className="flex justify-end">
              <Button
                size="sm"
                variant={showBoxes ? "outline" : "secondary"}
                onClick={() => setShowBoxes((prev) => !prev)}
              >
                {showBoxes ? "Скрыть подсветку" : "Показать подсветку"}
              </Button>
            </div>
          </div>
          {isLastDocument && (
            <Card className="rounded-3xl border bg-background">
              <CardHeader>
                <CardTitle className="text-lg">Отправка пакета</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-muted-foreground">
                <p>Проверьте, что все обязательные поля заполнены и подтверждены.</p>
              </CardContent>
              <CardFooter>
                <Button
                  onClick={() => void handleComplete()}
                  disabled={!canSubmit || isPending(`batch:${batch.id}:complete`)}
                >
                  Отправить на проверку
                </Button>
              </CardFooter>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

export default ResolvePage;


