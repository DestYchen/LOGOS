
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  bbox?: number[] | null;
  page?: number | null;
};

type CalibrationState = {
  scaleX: number;
  scaleY: number;
  offsetX: number;
  offsetY: number;
};

function DocumentViewer({ previews, highlight }: { previews: string[]; highlight: HighlightRegion | null }) {
  const [origin, setOrigin] = useState({ x: 50, y: 50 });
  const [dims, setDims] = useState({ naturalWidth: 0, naturalHeight: 0, width: 0, height: 0 });
  const [isHovered, setIsHovered] = useState(false);
  const [calibration, setCalibration] = useState<CalibrationState>({
    scaleX: 1,
    scaleY: 1,
    offsetX: 0,
    offsetY: 0,
  });
  const imgRef = useRef<HTMLImageElement | null>(null);

  const imageIndex = highlight?.page && highlight.page > 0 ? Math.min(highlight.page - 1, previews.length - 1) : 0;
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

  const overlayStyle = useMemo(() => {
    const bbox = highlight?.bbox;
    if (!bbox || bbox.length !== 4 || dims.naturalWidth === 0 || dims.naturalHeight === 0) {
      return null;
    }
    const [x1, y1, x2, y2] = bbox;
    const baseScaleX = dims.width / dims.naturalWidth;
    const baseScaleY = dims.height / dims.naturalHeight;
    const adjustedScaleX = baseScaleX * calibration.scaleX;
    const adjustedScaleY = baseScaleY * calibration.scaleY;
    const adjustedWidth = Math.max((x2 - x1) * adjustedScaleX, 2);
    const adjustedHeight = Math.max((y2 - y1) * adjustedScaleY, 2);
    return {
      left: `${x1 * adjustedScaleX + calibration.offsetX}px`,
      top: `${y1 * adjustedScaleY + calibration.offsetY}px`,
      width: `${adjustedWidth}px`,
      height: `${adjustedHeight}px`,
      transformOrigin: `${origin.x}% ${origin.y}%`,
      transform: `scale(${isHovered ? 3 : 1})`,
    };
  }, [highlight, dims, origin, isHovered, calibration]);

  const highlightCoversDocument = Boolean(highlight) && (!highlight?.bbox || highlight.bbox.length !== 4);

  const handleCalibrationChange = useCallback(
    (key: keyof CalibrationState) => (event: React.ChangeEvent<HTMLInputElement>) => {
      setCalibration((prev) => ({ ...prev, [key]: Number(event.target.value) }));
    },
    [],
  );

  const resetCalibration = useCallback(() => {
    setCalibration({ scaleX: 1, scaleY: 1, offsetX: 0, offsetY: 0 });
  }, []);

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
              alt="РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ РґРѕРєСѓРјРµРЅС‚Р°"
              onLoad={updateSizes}
              style={{
                transformOrigin: `${origin.x}% ${origin.y}%`,
                transform: `scale(${isHovered ? 3 : 1})`,
              }}
              className="h-full w-full object-contain transition-transform duration-200 ease-out"
            />
            {overlayStyle ? (
              <div
                className="pointer-events-none absolute border-4 border-primary/80 bg-primary/10 shadow-lg transition-transform"
                style={overlayStyle}
              />
            ) : null}
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            РџСЂРµРІСЊСЋ РґРѕРєСѓРјРµРЅС‚Р° РЅРµРґРѕСЃС‚СѓРїРЅРѕ
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-dashed border-primary/40 bg-primary/5 p-4 text-xs">
        <div className="mb-3 flex items-center justify-between">
          <span className="font-medium text-foreground">BBox tuning (temporary)</span>
          <Button size="sm" variant="ghost" onClick={resetCalibration}>
            Reset
          </Button>
        </div>
        <p className="mb-3 text-muted-foreground">
          Use these sliders to align the highlight box. Values are not persisted.
        </p>
        <div className="grid gap-3 text-foreground">
          <div>
            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
              <span>Scale X</span>
              <span>{calibration.scaleX.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0.5"
              max="1.5"
              step="0.01"
              value={calibration.scaleX}
              onChange={handleCalibrationChange("scaleX")}
              className="mt-1 w-full"
            />
          </div>
          <div>
            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
              <span>Scale Y</span>
              <span>{calibration.scaleY.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0.5"
              max="1.5"
              step="0.01"
              value={calibration.scaleY}
              onChange={handleCalibrationChange("scaleY")}
              className="mt-1 w-full"
            />
          </div>
          <div>
            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
              <span>Offset X</span>
              <span>{Math.round(calibration.offsetX)}</span>
            </div>
            <input
              type="range"
              min="-200"
              max="200"
              step="1"
              value={calibration.offsetX}
              onChange={handleCalibrationChange("offsetX")}
              className="mt-1 w-full"
            />
          </div>
          <div>
            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
              <span>Offset Y</span>
              <span>{Math.round(calibration.offsetY)}</span>
            </div>
            <input
              type="range"
              min="-200"
              max="200"
              step="1"
              value={calibration.offsetY}
              onChange={handleCalibrationChange("offsetY")}
              className="mt-1 w-full"
            />
          </div>
        </div>
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
      setError(new Error("РќРµ СѓРєР°Р·Р°РЅ РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂ РїР°РєРµС‚Р°"));
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
      setMessage("РўРёРї РґРѕРєСѓРјРµРЅС‚Р° СЃРѕС…СЂР°РЅС‘РЅ");
    });
  };

  const handleRefill = async (doc: DocumentPayload) => {
    await withAction(`doc:${doc.id}:refill`, async () => {
      await refillDocument(doc.id);
      await waitForDocument(doc.id);
      setMessage("Р”РѕРєСѓРјРµРЅС‚ РїРµСЂРµСЂР°СЃС‡РёС‚Р°РЅ");
    });
  };

  const handleDelete = async (doc: DocumentPayload) => {
    if (!window.confirm("РЈРґР°Р»РёС‚СЊ РґРѕРєСѓРјРµРЅС‚ РёР· РїР°РєРµС‚Р°?")) {
      return;
    }
    await withAction(`doc:${doc.id}:delete`, async () => {
      await deleteDocument(doc.id);
      await fetchAndSelect(Math.max(activeIndex - 1, 0));
      setMessage("Р”РѕРєСѓРјРµРЅС‚ СѓРґР°Р»С‘РЅ");
    });
  };

  const handleSaveField = async (doc: DocumentPayload, field: FieldState) => {
    const value = draftValue(doc.id, field.field_key).trim();
    await withAction(`field:${doc.id}:${field.field_key}:save`, async () => {
      await updateField(doc.id, field.field_key, value === "" ? null : value);
      await fetchAndSelect(activeIndex);
      setMessage("РџРѕР»Рµ СЃРѕС…СЂР°РЅРµРЅРѕ");
    });
  };

  const handleConfirmField = async (doc: DocumentPayload, field: FieldState) => {
    await withAction(`field:${doc.id}:${field.field_key}:confirm`, async () => {
      await confirmField(doc.id, field.field_key);
      await fetchAndSelect(activeIndex);
      setMessage("РџРѕР»Рµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРѕ");
    });
  };

  const handleComplete = async () => {
    if (!batch) return;
    await withAction(`batch:${batch.id}:complete`, async () => {
      await completeBatch(batch.id);
      setMessage("РџР°РєРµС‚ РѕС‚РїСЂР°РІР»РµРЅ РЅР° РїСЂРѕРІРµСЂРєСѓ");
      setTimeout(() => navigate(`/table/${batch.id}`), 1000);
    });
  };

  const goToDocument = (index: number) => {
    setHighlightedField(null);
    setActiveIndex(index);
    navigate(`/resolve/${batchId}/${index}`, { replace: true });
  };

  if (!batchId) {
    return <Alert variant="destructive">РќРµ СѓРєР°Р·Р°РЅ РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂ РїР°РєРµС‚Р°.</Alert>;
  }

  if (loading) {
    return (
      <div className="flex h-80 items-center justify-center text-muted-foreground">
        <Spinner className="mr-3" /> Р—Р°РіСЂСѓР·РєР° РїР°РєРµС‚Р°...
      </div>
    );
  }

  if (error) {
    return <Alert variant="destructive">{error.message}</Alert>;
  }

  if (!batch || !currentDoc) {
    return <Alert variant="info">Р”РѕРєСѓРјРµРЅС‚С‹ РЅРµРґРѕСЃС‚СѓРїРЅС‹ РґР»СЏ РѕР±СЂР°Р±РѕС‚РєРё.</Alert>;
  }

  const totalDocs = documents.length;
  const isLastDocument = totalDocs > 0 && activeIndex === totalDocs - 1;
  const canSubmit = batch.pending_total === 0 && !batch.awaiting_processing;

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Р”РѕРєСѓРјРµРЅС‚ вЂ” РёСЃРїСЂР°РІР»РµРЅРёРµ РѕС€РёР±РѕРє</h1>
        <p className="text-muted-foreground">РџР°РєРµС‚ {batch.id.slice(0, 8)} В· РЎС‚Р°С‚СѓСЃ РїР°РєРµС‚Р°:</p>
        <div className="mt-1">
          <StatusPill status={mapBatchStatus(batch.status)} />
        </div>
        <p className="text-sm text-muted-foreground">РЎРѕР·РґР°РЅ {formatDateTime(batch.created_at)} В· Р”РѕРєСѓРјРµРЅС‚РѕРІ: {totalDocs}</p>
      </header>

      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">
          Р”РѕРєСѓРјРµРЅС‚ {activeIndex + 1} РёР· {totalDocs}
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
              aria-label={`Р”РѕРєСѓРјРµРЅС‚ ${index + 1}`}
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
                <Label>РўРёРї РґРѕРєСѓРјРµРЅС‚Р°</Label>
                <Select
                  value={currentDoc.doc_type}
                  onValueChange={(value) => void handleSetType(currentDoc, value)}
                  disabled={isPending(`doc:${currentDoc.id}:type`)}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue placeholder="Р’С‹Р±РµСЂРёС‚Рµ С‚РёРї" />
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
                  РЈРґР°Р»РёС‚СЊ РґРѕРєСѓРјРµРЅС‚
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void handleRefill(currentDoc)}
                  disabled={isPending(`doc:${currentDoc.id}:refill`)}
                >
                  РЎРѕС…СЂР°РЅРёС‚СЊ Рё РїРµСЂРµСЃС‡РёС‚Р°С‚СЊ
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-3xl border bg-background">
            <CardHeader>
              <CardTitle className="text-lg">РџСЂРѕР±Р»РµРјС‹ РґР»СЏ РёСЃРїСЂР°РІР»РµРЅРёСЏ</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <section className="space-y-3">
                <h2 className="text-sm font-semibold">РћР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ РїРѕР»СЏ</h2>
                {grouped.required.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Р’СЃРµ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ РїРѕР»СЏ Р·Р°РїРѕР»РЅРµРЅС‹.</p>
                ) : (
                  grouped.required.map((field) => (
                    <div key={field.field_key} className="rounded-xl border border-amber-400/40 bg-amber-500/10 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium">{field.field_key}</p>
                          <p className="text-xs text-muted-foreground">РўСЂРµР±СѓРµС‚СЃСЏ Р·Р°РїРѕР»РЅРёС‚СЊ РїРѕР»Рµ</p>
                        </div>
                        <Badge variant="warning">РћР±СЏР·Р°С‚РµР»СЊРЅРѕ</Badge>
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
                          РЎРѕС…СЂР°РЅРёС‚СЊ Рё РїСЂРѕРґРѕР»Р¶РёС‚СЊ
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setHighlightedField({ fieldKey: field.field_key, bbox: field.bbox ?? null, page: field.page ?? null })}
                        >
                          РџРѕРєР°Р·Р°С‚СЊ РЅР° РґРѕРєСѓРјРµРЅС‚Рµ
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </section>

              <section className="space-y-3">
                <h2 className="text-sm font-semibold">РџРѕР»СЏ СЃ РЅРёР·РєРѕР№ СѓРІРµСЂРµРЅРЅРѕСЃС‚СЊСЋ</h2>
                {grouped.lowConfidence.length === 0 ? (
                  <p className="text-sm text-muted-foreground">РќРµС‚ РїРѕР»РµР№ СЃ РЅРёР·РєРѕР№ СѓРІРµСЂРµРЅРЅРѕСЃС‚СЊСЋ.</p>
                ) : (
                  grouped.lowConfidence.map((field) => (
                    <div key={field.field_key} className="rounded-xl border border-primary/30 bg-primary/5 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium">{field.field_key}</p>
                          <p className="text-xs text-muted-foreground">
                            РЈРІРµСЂРµРЅРЅРѕСЃС‚СЊ: {field.confidence_display ?? "вЂ”"}
                          </p>
                        </div>
                        <Button size="sm" variant="ghost" onClick={() => setHighlightedField({ fieldKey: field.field_key, bbox: field.bbox ?? null, page: field.page ?? null })}>
                          РџРѕРєР°Р·Р°С‚СЊ РЅР° РґРѕРєСѓРјРµРЅС‚Рµ
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
                          РР·РјРµРЅРёС‚СЊ
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void handleConfirmField(currentDoc, field)}
                          disabled={isPending(`field:${currentDoc.id}:${field.field_key}:confirm`)}
                        >
                          РџРѕРґС‚РІРµСЂРґРёС‚СЊ
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
                    РЎРЅСЏС‚СЊ РїРѕРґСЃРІРµС‚РєСѓ
                  </Button>
                  <div className="space-y-2 rounded-xl border border-muted bg-muted/20 p-3">
                    {grouped.other.map((field) => (
                      <div key={field.field_key} className="rounded-lg bg-background px-3 py-2 text-sm">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{field.field_key}</span>
                          <span className="text-xs text-muted-foreground">{field.reason}</span>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">{field.value ?? "вЂ”"}</p>
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
                  РЎР»РµРґСѓСЋС‰РёР№ РґРѕРєСѓРјРµРЅС‚
                </Button>
              ) : null}
            </CardFooter>
          </Card>
        </div>

        <div className="space-y-6">
          <DocumentViewer previews={currentDoc.previews} highlight={highlightedField} />
          {isLastDocument && (
            <Card className="rounded-3xl border bg-background">
              <CardHeader>
                <CardTitle className="text-lg">РћС‚РїСЂР°РІРєР° РїР°РєРµС‚Р°</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-muted-foreground">
                <p>РџСЂРѕРІРµСЂСЊС‚Рµ, С‡С‚Рѕ РІСЃРµ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ РїРѕР»СЏ Р·Р°РїРѕР»РЅРµРЅС‹ Рё РїРѕРґС‚РІРµСЂР¶РґРµРЅС‹.</p>
              </CardContent>
              <CardFooter>
                <Button
                  onClick={() => void handleComplete()}
                  disabled={!canSubmit || isPending(`batch:${batch.id}:complete`)}
                >
                  РћС‚РїСЂР°РІРёС‚СЊ РЅР° РїСЂРѕРІРµСЂРєСѓ
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


