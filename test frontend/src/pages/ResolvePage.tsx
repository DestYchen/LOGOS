

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { Check, ChevronDown, ChevronRight, Eye, EyeOff, Pencil, SlidersHorizontal, X } from "lucide-react";

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

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

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
import { DOCUMENT_PREVIEW_CALIBRATION } from "../lib/preview-calibration";

import { formatPacketTimestamp } from "../lib/packet";

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



const CALIBRATION: CalibrationState = { ...DOCUMENT_PREVIEW_CALIBRATION };



const HIDDEN_FIELD_KEYS = new Set(["producs", "products"]);



const DEFAULT_VIEWER_HEIGHT = 640;



const MISSING_PLACEHOLDER = "-";





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



function normalizeBBox(bbox: unknown): number[] | null {

  if (!bbox) return null;

  if (Array.isArray(bbox)) {

    if (bbox.length !== 4) return null;

    const values = bbox.map((value) => Number(value));

    return values.every((value) => Number.isFinite(value)) ? values : null;

  }

  if (typeof bbox === "object") {

    const record = bbox as Record<string, unknown>;

    const extract = (keys: string[], transform?: (values: number[]) => number[]) => {

      const raw = keys.map((key) => record[key]);

      if (raw.some((value) => value === undefined || value === null)) {

        return null;

      }

      const numbers = raw.map((value) => Number(value));

      if (!numbers.every((value) => Number.isFinite(value))) {

        return null;

      }

      return transform ? transform(numbers) : numbers;

    };

    return (

      extract(["x1", "y1", "x2", "y2"]) ??

      extract(["left", "top", "right", "bottom"]) ??

      extract(["x", "y", "width", "height"], ([x, y, width, height]) => [x, y, x + width, y + height]) ??

      null

    );

  }

  return null;

}



function DocumentViewer({

  previews,

  highlight,

  boxes,

  showBoxes,

  onToggleBoxes,

}: {

  previews: string[];

  highlight: HighlightRegion | null;

  boxes: OverlayBox[];

  showBoxes: boolean;

  onToggleBoxes: () => void;

}) {

  const [origin, setOrigin] = useState({ x: 50, y: 50 });

  const [dims, setDims] = useState({ naturalWidth: 0, naturalHeight: 0, width: 0, height: 0 });

  const [isHovered, setIsHovered] = useState(false);

  const [isControlHovered, setIsControlHovered] = useState(false);

  const [calibration, setCalibration] = useState<CalibrationState>({ ...CALIBRATION });

  const [showCalibrationPanel, setShowCalibrationPanel] = useState(false);

  const imgRef = useRef<HTMLImageElement | null>(null);



  const imageIndex = highlight?.page && highlight.page > 0 ? Math.min(highlight.page - 1, previews.length - 1) : 0;

  const currentPage = imageIndex + 1;

  const src = previews[imageIndex] ?? previews[0];



  const updateSizes = useCallback(() => {

    if (!imgRef.current) return;

    const { naturalWidth, naturalHeight, clientWidth, clientHeight } = imgRef.current;

    setDims({ naturalWidth, naturalHeight, width: clientWidth, height: clientHeight });

  }, []);



  const onMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {

    if (isControlHovered) return;

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

      const padding = 6;

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

          left: `${left - padding}px`,

          top: `${top - padding}px`,

          width: `${width + padding * 2}px`,

          height: `${height + padding * 2}px`,

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

      boxShadow: "0 0 10px rgba(0,0,0,0.18)",

      borderRadius: "14px",

    }}

  />

);



  return (

    <div className="space-y-4">

      <div

        className={cn(

          "group relative aspect-[3/4] max-h-[640px] overflow-hidden rounded-3xl border bg-background shadow-lg transition-colors lg:max-h-none",

          highlightCoversDocument ? "border-4 border-primary/70" : "",

        )}

        onMouseMove={onMouseMove}

        onMouseEnter={() => {

          if (!isControlHovered) {

            setIsHovered(true);

          }

        }}

        onMouseLeave={() => {

          setIsHovered(false);

          setIsControlHovered(false);

        }}

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

            <div className="pointer-events-none absolute inset-0">

              <div

                className="pointer-events-auto absolute right-4 top-4 flex gap-2"

                onMouseEnter={(event) => {

                  event.stopPropagation();

                  setIsControlHovered(true);

                  setIsHovered(false);

                }}

                onMouseLeave={(event) => {

                  event.stopPropagation();

                  setIsControlHovered(false);

                  setIsHovered(false);

                }}

              >

                <Button

                  size="icon"

                  variant="secondary"

                  aria-label={showBoxes ? "Скрыть подсветку полей" : "Показать подсветку полей"}

                  onClick={onToggleBoxes}

                  className="shadow-sm"

                >

                  {showBoxes ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}

                </Button>

                <Button

                  size="icon"

                  variant="outline"

                  aria-label="Настроить калибровку"

                  onClick={(event) => {

                    event.stopPropagation();

                    setShowCalibrationPanel((prev) => !prev);

                  }}

                  className="shadow-sm"

                >

                  <SlidersHorizontal className="h-4 w-4" />

                </Button>

              </div>

              {showCalibrationPanel ? (

                <div className="pointer-events-auto absolute right-4 top-16 w-48 rounded-xl border bg-background/95 p-3 shadow-lg">

                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Калибровка</p>

                  <div className="space-y-2 text-xs">

                    <label className="flex items-center justify-between gap-2">

                      <span>Scale X</span>

                      <input

                        type="number"

                        step="0.01"

                        value={calibration.scaleX}

                        onChange={(event) =>

                          setCalibration((prev) => ({

                            ...prev,

                            scaleX: Number.parseFloat(event.target.value) || prev.scaleX,

                          }))

                        }

                        className="w-20 rounded-md border px-2 py-1 text-right"

                      />

                    </label>

                    <label className="flex items-center justify-between gap-2">

                      <span>Scale Y</span>

                      <input

                        type="number"

                        step="0.01"

                        value={calibration.scaleY}

                        onChange={(event) =>

                          setCalibration((prev) => ({

                            ...prev,

                            scaleY: Number.parseFloat(event.target.value) || prev.scaleY,

                          }))

                        }

                        className="w-20 rounded-md border px-2 py-1 text-right"

                      />

                    </label>

                    <label className="flex items-center justify-between gap-2">

                      <span>Offset X</span>

                      <input

                        type="number"

                        step="0.5"

                        value={calibration.offsetX}

                        onChange={(event) =>

                          setCalibration((prev) => ({

                            ...prev,

                            offsetX: Number.parseFloat(event.target.value) || prev.offsetX,

                          }))

                        }

                        className="w-20 rounded-md border px-2 py-1 text-right"

                      />

                    </label>

                    <label className="flex items-center justify-between gap-2">

                      <span>Offset Y</span>

                      <input

                        type="number"

                        step="0.5"

                        value={calibration.offsetY}

                        onChange={(event) =>

                          setCalibration((prev) => ({

                            ...prev,

                            offsetY: Number.parseFloat(event.target.value) || prev.offsetY,

                          }))

                        }

                        className="w-20 rounded-md border px-2 py-1 text-right"

                      />

                    </label>

                  </div>

                  <div className="mt-3 flex gap-2">

                    <Button

                      size="sm"

                      variant="secondary"

                      className="flex-1"

                      onClick={(event) => {

                        event.stopPropagation();

                        setCalibration({ ...CALIBRATION });

                      }}

                    >

                      Сбросить

                    </Button>

                    <Button

                      size="sm"

                      variant="ghost"

                      className="flex-1"

                      onClick={(event) => {

                        event.stopPropagation();

                        setShowCalibrationPanel(false);

                        setIsControlHovered(false);

                      }}

                    >

                      Закрыть

                    </Button>

                  </div>

                </div>

              ) : null}

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

  const [showResolvedFields, setShowResolvedFields] = useState(false);

  const [editingFieldKey, setEditingFieldKey] = useState<string | null>(null);

  const viewerPlaceholderRef = useRef<HTMLDivElement | null>(null);

  const viewerContainerRef = useRef<HTMLDivElement | null>(null);

  const [viewerPosition, setViewerPosition] = useState<{ top: number; left: number; width: number } | null>(null);

  const [viewerHeight, setViewerHeight] = useState<number>(0);



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

    const unique = new Map<string, OverlayBox>();

    currentDoc.fields.forEach((field) => {

      const bbox = normalizeBBox(field.bbox);

      if (!bbox) return;

      const page = field.page ?? null;

      const key = `${page ?? "?"}|${bbox.join(",")}`;

      if (!unique.has(key)) {

        unique.set(key, {

          fieldKey: field.field_key,

          bbox,

          page,

        });

      }

    });

    return Array.from(unique.values());

  }, [currentDoc]);



  const updateViewerPosition = useCallback(() => {

    const placeholder = viewerPlaceholderRef.current;

    if (!placeholder) return;

    const rect = placeholder.getBoundingClientRect();

    const viewportHeight = window.innerHeight || document.documentElement?.clientHeight || DEFAULT_VIEWER_HEIGHT;

    const viewerRectHeight = viewerHeight || DEFAULT_VIEWER_HEIGHT;

    const minTop = 16;

    const maxTop = Math.max(viewportHeight - viewerRectHeight - 16, minTop);

    const safeTop = Math.min(Math.max(rect.top, minTop), maxTop);

    setViewerPosition({ top: safeTop, left: rect.left, width: rect.width });

  }, [viewerHeight]);



  useLayoutEffect(() => {

    updateViewerPosition();

  }, [updateViewerPosition, activeIndex, currentDoc?.id, viewerHeight, actionError, message]);



  useEffect(() => {

    const handleResize = () => {

      updateViewerPosition();

    };

    const handleScroll = () => {

      updateViewerPosition();

    };

    window.addEventListener("resize", handleResize);

    window.addEventListener("scroll", handleScroll, { passive: true });

    return () => {

      window.removeEventListener("resize", handleResize);

      window.removeEventListener("scroll", handleScroll);

    };

  }, [updateViewerPosition]);



  useEffect(() => {

    const container = viewerContainerRef.current;

    if (!container) return;

    const setHeight = () => {

      setViewerHeight(container.getBoundingClientRect().height);

    };

    setHeight();

    if (typeof ResizeObserver === "undefined") {

      return;

    }

    const observer = new ResizeObserver((entries) => {

      for (const entry of entries) {

        setViewerHeight(entry.contentRect.height);

      }

    });

    observer.observe(container);

    return () => observer.disconnect();

  }, [viewerPosition, currentDoc?.id]);



  useEffect(() => {

    setShowBoxes(false);

    setShowResolvedFields(false);

    setEditingFieldKey(null);

  }, [activeIndex]);



  const grouped = useMemo(() => {

    if (!currentDoc) {

      return { required: [] as FieldState[], lowConfidence: [] as FieldState[], other: [] as FieldState[] };

    }

    // Show only schema-defined fields coming from the API. The backend marks
    // stale DB fields that aren't in the current schema as reason === "extra".
    // Filter those out so the UI reflects docs_json_2-only fields.
    const visibleFields = currentDoc.fields.filter(
      (field) => !HIDDEN_FIELD_KEYS.has(field.field_key) && field.reason !== "extra"
    );
    const required = visibleFields.filter((field) => field.reason === "missing");

    const lowConfidence = visibleFields.filter((field) => field.reason === "low_confidence");

    const other = visibleFields.filter((field) => field.reason !== "missing" && field.reason !== "low_confidence");

    return { required, lowConfidence, other };

  }, [currentDoc]);

  const productTable = currentDoc?.products;
  const productColumns = productTable?.columns ?? [];
  const productGroups = useMemo(() => {
    if (!currentDoc) {
      return [];
    }
    const groups = new Map<string, { order: number; fields: Record<string, FieldState> }>();
    currentDoc.fields.forEach((field) => {
      if (!field.field_key.startsWith("products.")) {
        return;
      }
      const parts = field.field_key.split(".");
      if (parts.length < 3) {
        return;
      }
      const productKey = parts[1];
      const subKey = parts.slice(2).join(".");
      const match = productKey.match(/(\d+)/);
      const order = match ? Number.parseInt(match[1], 10) : Number.MAX_SAFE_INTEGER;
      const entry = groups.get(productKey) ?? { order, fields: {} };
      entry.fields[subKey] = field;
      groups.set(productKey, entry);
    });
    return Array.from(groups.entries())
      .map(([key, value]) => ({
        key,
        order: value.order,
        fields: value.fields,
      }))
      .sort((a, b) => a.order - b.order);
  }, [currentDoc]);
  const hasProducts = productGroups.length > 0 && productColumns.length > 0;



  const toggleFieldHighlight = useCallback((field: FieldState) => {

    const normalizedBBox = normalizeBBox(field.bbox);

    const next: HighlightState = {

      fieldKey: field.field_key,

      bbox: normalizedBBox,

      page: field.page ?? null,

    };

    setHighlightedField((prev) => {

      if (!prev) return next;

      const sameField = prev.fieldKey === next.fieldKey;

      const samePage = (prev.page ?? null) === (next.page ?? null);

      const prevBBox = prev.bbox ?? null;

      const nextBBox = next.bbox ?? null;

      const sameBBox =

        (!prevBBox && !nextBBox) ||

        (prevBBox &&

          nextBBox &&

          prevBBox.length === nextBBox.length &&

          prevBBox.every((value, index) => value === nextBBox[index]));

      return sameField && samePage && sameBBox ? null : next;

    });

  }, [setHighlightedField]);



  const handleToggleBoxes = useCallback(() => {

    setShowBoxes((prev) => {

      const next = !prev;

      if (!next) {

        setHighlightedField(null);

      }

      return next;

    });

  }, [setShowBoxes, setHighlightedField]);



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



  // Save current document type and recalculate fields in one click

  const handleSaveAndRecalc = async (doc: DocumentPayload) => {

    await withAction(`doc:${doc.id}:refill`, async () => {

      await setDocumentType(doc.id, doc.doc_type);

      await waitForDocument(doc.id);

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



  const saveFieldValue = async (

    doc: DocumentPayload,

    field: FieldState,

    value: string | null,

    actionKey: string,

    successMessage: string,

  ) => {

    await withAction(actionKey, async () => {

      await updateField(doc.id, field.field_key, value);

      await fetchAndSelect(activeIndex);

      setMessage(successMessage);

    });

  };



  const handleSaveField = async (doc: DocumentPayload, field: FieldState) => {

    const value = draftValue(doc.id, field.field_key).trim();

    await saveFieldValue(

      doc,

      field,

      value === "" ? null : value,

      `field:${doc.id}:${field.field_key}:save`,

      "Поле сохранено",

    );

  };



  const handleConfirmRequiredField = async (doc: DocumentPayload, field: FieldState) => {

    const value = draftValue(doc.id, field.field_key).trim();

    if (value === "") {

      return;

    }

    await withAction(`field:${doc.id}:${field.field_key}:resolve`, async () => {

      await updateField(doc.id, field.field_key, value === "" ? null : value);

      await confirmField(doc.id, field.field_key);

      await fetchAndSelect(activeIndex);

      setMessage("Поле подтверждено");

    });

  };



  const handleMarkFieldMissing = async (doc: DocumentPayload, field: FieldState) => {

    updateDraft(doc.id, field.field_key, MISSING_PLACEHOLDER);

    await withAction(`field:${doc.id}:${field.field_key}:missing`, async () => {

      await updateField(doc.id, field.field_key, MISSING_PLACEHOLDER);

      await confirmField(doc.id, field.field_key);

      await fetchAndSelect(activeIndex);

      setMessage("Поле сохранено с пустым значением");

    });

  };



  const handleResolveLowConfidence = async (doc: DocumentPayload, field: FieldState) => {

    const value = draftValue(doc.id, field.field_key).trim();

    if (value === "") {

      return;

    }

    await withAction(`field:${doc.id}:${field.field_key}:resolve`, async () => {

      if (field.editable) {

        const normalizedCurrent = (field.value ?? "").trim();

        if (value !== normalizedCurrent) {

          await updateField(doc.id, field.field_key, value === "" ? null : value);

        }

      }

      await confirmField(doc.id, field.field_key);

      await fetchAndSelect(activeIndex);

      setMessage("Поле подтверждено");

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

    <div className="space-y-6">

      <header className="space-y-1">

        <h1 className="text-2xl font-semibold">Документ — исправление ошибок</h1>

        <p className="text-muted-foreground">Пакет {formatPacketTimestamp(batch.created_at)} · Статус пакета:</p>

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

                "h-4 w-4 rounded-full border-2 transition-colors",

                index === activeIndex

                  ? "border-primary bg-primary"

                  : "border-muted-foreground/40 bg-muted-foreground/30 hover:border-primary hover:bg-primary/50",

              )}

              aria-label={`Документ ${index + 1}`}

            />

          ))}

        </div>

      </div>



      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(420px,38vw)]">

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

                  onClick={() => void handleSaveAndRecalc(currentDoc)}

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

                  <p className="text-sm text-muted-foreground">Нет обязательных полей для заполнения.</p>

                ) : (

                  grouped.required.map((field) => {

                    const confirmKey = `field:${currentDoc.id}:${field.field_key}:resolve`;

                    const missingKey = `field:${currentDoc.id}:${field.field_key}:missing`;

                    const isBusy = isPending(confirmKey) || isPending(missingKey);

                    const currentDraft = draftValue(currentDoc.id, field.field_key);

                    const isConfirmDisabled = isBusy || currentDraft.trim() === "";

                    return (

                      <div key={field.field_key} className="rounded-xl border border-amber-400/40 bg-amber-500/10 p-4">

                        <div className="flex flex-wrap items-start justify-between gap-3">

                          <div>

                            <p className="text-sm font-medium">{field.field_key}</p>

                            <p className="text-xs text-muted-foreground">Введите значение вручную для этого поля</p>

                          </div>

                          <Badge variant="warning">Обязательно</Badge>

                        </div>

                        <div className="mt-3 flex items-center gap-2">

                          <Input

                            className="flex-1"

                            value={currentDraft}

                            onChange={(event) => updateDraft(currentDoc.id, field.field_key, event.target.value)}

                          />

                          <Button

                            size="icon"

                            variant="secondary"

                            aria-label="Save field"

                            onClick={() => void handleConfirmRequiredField(currentDoc, field)}

                            disabled={isConfirmDisabled}

                          >

                            <Check className="h-4 w-4" />

                          </Button>

                          <Button

                            size="icon"

                            variant="ghost"

                            aria-label="Mark field missing"

                            onClick={() => void handleMarkFieldMissing(currentDoc, field)}

                            disabled={isBusy}

                          >

                            <X className="h-4 w-4" />

                          </Button>

                        </div>

                      </div>

                    );

                  })

                )}

              </section>

              <section className="space-y-3">

                <h2 className="text-sm font-semibold">Поля с низкой уверенностью</h2>

                {grouped.lowConfidence.length === 0 ? (

                  <p className="text-sm text-muted-foreground">Таких полей нет.</p>

                ) : (

                  grouped.lowConfidence.map((field) => {

                    const resolveKey = `field:${currentDoc.id}:${field.field_key}:resolve`;

                    const isResolving = isPending(resolveKey);

                    const currentDraft = draftValue(currentDoc.id, field.field_key);

                    const trimmedDraft = currentDraft.trim();

                    const isHighlighted =

                      highlightedField?.fieldKey === field.field_key &&

                      (highlightedField?.page ?? null) === (field.page ?? null);

                    const isConfirmDisabled = isResolving || trimmedDraft === "";

                    return (

                      <div key={field.field_key} className="rounded-xl border border-sky-400/40 bg-sky-500/10 p-4">

                        <div className="flex flex-wrap items-start justify-between gap-3">

                          <div>

                            <p className="text-sm font-medium">{field.field_key}</p>

                            <p className="text-xs text-muted-foreground">

                              Уверенность: {field.confidence_display ?? ""}

                            </p>

                          </div>

                          <Badge variant="outline">Низкая уверенность</Badge>

                        </div>

                        <div className="mt-3 flex items-center gap-2">

                          <Input

                            className="flex-1"

                            value={currentDraft}

                            onChange={(event) => updateDraft(currentDoc.id, field.field_key, event.target.value)}

                          />

                          <Button

                            size="icon"

                            variant={isHighlighted ? "secondary" : "outline"}

                            aria-label="Highlight field"

                            onClick={() => {

                              toggleFieldHighlight(field);

                            }}

                            disabled={isResolving}

                          >

                            {isHighlighted ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}

                          </Button>

                          <Button

                            size="icon"

                            variant="secondary"

                            aria-label="Confirm value"

                            onClick={() => void handleResolveLowConfidence(currentDoc, field)}

                            disabled={isConfirmDisabled}

                          >

                            <Check className="h-4 w-4" />

                          </Button>

                        </div>

                      </div>

                    );

                  })

                )}

              </section>

              {grouped.other.length ? (

                <section className="space-y-3">

                  <button

                    type="button"

                    onClick={() => {

                      setShowResolvedFields((prev) => {

                        const next = !prev;

                        if (!next) {

                          setEditingFieldKey(null);

                        }

                        return next;

                      });

                    }}

                    className="flex w-full items-center justify-between rounded-xl border border-transparent bg-muted/30 px-4 py-3 text-left text-sm font-medium transition hover:border-muted-foreground/40 hover:bg-muted/40"

                  >

                    <span>

                      Проверенные поля

                      <span className="ml-2 text-xs font-normal text-muted-foreground">( {grouped.other.length} )</span>

                    </span>

                    {showResolvedFields ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}

                  </button>

                  {showResolvedFields ? (

                    <div className="space-y-2 rounded-xl border border-muted bg-muted/20 p-3">

                      {grouped.other.map((field) => {

                        const fieldKey = `${currentDoc.id}:${field.field_key}`;

                        const isEditing = editingFieldKey === fieldKey;

                        const saveKey = `field:${currentDoc.id}:${field.field_key}:save`;

                        const isSaving = isPending(saveKey);

                        return (

                          <div key={field.field_key} className="rounded-lg bg-background px-3 py-3 text-sm">

                            <div className="flex items-start justify-between gap-2">

                              <div className="min-w-0">

                                <p className="font-medium leading-snug">{field.field_key}</p>

                                {!isEditing ? (

                                  <p className="mt-1 break-words text-sm text-muted-foreground">{field.value ?? ""}</p>

                                ) : null}

                              </div>

                              <div className="flex items-center gap-1">

                                <Button

                                  size="icon"

                                  variant="ghost"

                                  aria-label="Highlight field"

                                  onClick={() => {

                                    toggleFieldHighlight(field);

                                  }}

                                >

                                  <Eye className="h-4 w-4" />

                                </Button>

                                <Button

                                  size="icon"

                                  variant="ghost"

                                  aria-label="Edit field"

                                  onClick={() => {

                                    if (!isEditing) {

                                      updateDraft(currentDoc.id, field.field_key, draftValue(currentDoc.id, field.field_key));

                                    }

                                    setEditingFieldKey(isEditing ? null : fieldKey);

                                  }}

                                >

                                  <Pencil className="h-4 w-4" />

                                </Button>

                              </div>

                            </div>

                            {isEditing ? (

                              <div className="mt-3 flex items-center gap-2">

                                <Textarea

                                  className="flex-1"

                                  rows={4}

                                  value={draftValue(currentDoc.id, field.field_key)}

                                  onChange={(event) => updateDraft(currentDoc.id, field.field_key, event.target.value)}

                                  disabled={isSaving}

                                />

                                <div className="flex flex-col gap-2">

                                  <Button

                                    size="icon"

                                    variant="secondary"

                                    aria-label="Save field"

                                    onClick={() => {

                                      void handleSaveField(currentDoc, field).then(() => setEditingFieldKey(null));

                                    }}

                                    disabled={isSaving}

                                  >

                                    <Check className="h-4 w-4" />

                                  </Button>

                                  <Button

                                    size="icon"

                                    variant="ghost"

                                    aria-label="Cancel edit"

                                    onClick={() => {

                                      setEditingFieldKey(null);

                                      updateDraft(currentDoc.id, field.field_key, field.value ?? "");

                                    }}

                                    disabled={isSaving}

                                  >

                                    <X className="h-4 w-4" />

                                  </Button>

                                </div>

                              </div>

                            ) : null}

                          </div>

                        );

                      })}

                    </div>

                  ) : null}

                </section>

              ) : null}

              {hasProducts ? (
                <section className="space-y-3">
                  <h2 className="text-sm font-semibold">Товары</h2>
                  {productGroups.map((group, index) => {
                    const label =
                      group.order !== Number.MAX_SAFE_INTEGER ? `Продукт ${group.order + 1}` : `Продукт ${index + 1}`;
                    return (
                      <div
                        key={group.key ?? `product-${index}`}
                        className="space-y-3 rounded-2xl border border-muted/60 bg-muted/20 p-3"
                      >
                        <div className="text-sm font-semibold">{label}</div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          {productColumns.map((column) => {
                            const field = group.fields[column.key];
                            return (
                              <div
                                key={`${group.key ?? index}-${column.key}`}
                                className="rounded-xl border bg-background/80 p-3"
                              >
                                <p className="text-xs text-muted-foreground">{column.label}</p>
                                <div className="mt-1 flex items-center justify-between gap-2">
                                  <p className="break-words text-sm font-medium leading-snug">
                                    {field?.value ?? "—"}
                                  </p>
                                  {field ? (
                                    <Button
                                      size="icon"
                                      variant="ghost"
                                      aria-label="Показать поле на документе"
                                      onClick={() => toggleFieldHighlight(field)}
                                    >
                                      <Eye className="h-4 w-4" />
                                    </Button>
                                  ) : null}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </section>
              ) : null}

            </CardContent>



            <CardFooter className="flex flex-wrap items-center justify-end gap-3">

              <Button variant="outline" onClick={() => navigate(`/table/${batch.id}`)}>
                Вернуться к таблице
              </Button>

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

        <div

          className="hidden lg:block"

          ref={viewerPlaceholderRef}

          style={{ minHeight: viewerHeight || DEFAULT_VIEWER_HEIGHT }}

        />

      </div>



      <div className="space-y-3 lg:hidden">

        <DocumentViewer

          previews={currentDoc.previews}

          highlight={highlightedField}

          boxes={overlayBoxes}

          showBoxes={showBoxes}

          onToggleBoxes={handleToggleBoxes}

        />

      </div>

      {isLastDocument && (
        <Card className="rounded-3xl border bg-background">
          <CardHeader>
            <CardTitle className="text-lg">Финальный этап</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>Убедитесь, что все обязательные поля заполнены и подтверждены.</p>
          </CardContent>
          <CardFooter>
            <Button
              variant="secondary"
              onClick={() => navigate(`/table/${batch.id}`)}
            >
              Вернуться к таблице
            </Button>
          </CardFooter>
        </Card>
      )}

      {viewerPosition ? (

        <div

          ref={viewerContainerRef}

          className="hidden lg:block"

          style={{

            position: "fixed",

            top: viewerPosition.top,

            left: viewerPosition.left,

            width: viewerPosition.width,

            zIndex: 30,

          }}

        >

          <DocumentViewer

            previews={currentDoc.previews}

            highlight={highlightedField}

            boxes={overlayBoxes}

            showBoxes={showBoxes}

            onToggleBoxes={handleToggleBoxes}

          />

        </div>

      ) : null}

    </div>

  );

}



export default ResolvePage;

