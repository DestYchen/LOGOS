import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Spinner } from "../components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Textarea } from "../components/ui/textarea";
import { useHistoryContext } from "../contexts/history-context";
import { confirmField, fetchBatchDetails, updateField } from "../lib/api";
import { cn, formatDateTime, mapBatchStatus, statusLabel } from "../lib/utils";
import { formatPacketTimestamp } from "../lib/packet";
import type { BatchDetails, DocumentPayload, FieldState } from "../types/api";

type ValidationRef = {
  doc_id?: string;
  doc_type?: string;
  field_key?: string;
  label?: string;
  message?: string;
  present?: boolean;
  note?: string;
};

type ValidationEntry = {
  ruleId: string;
  severity: string;
  message: string;
  refs: ValidationRef[];
};

type SelectedCell = {
  docId: string;
  fieldKey: string;
  value: string | null;
  confidence: number | null;
};

type ProductIssue = {
  severity: string;
  message: string;
};

type ProductMatrixRow = {
  key: string;
  docId: string | null;
  docType: string | null;
  filename: string | null;
  field: string;
  cells: Record<
    string,
    {
      value: string | null;
      confidence: number | null;
      issues: ProductIssue[];
    }
  >;
};

type DocPresenceItem = {
  docType: string;
  present: boolean;
  filenames: string[];
  count: number;
};

const EMPTY_DOC_ID = "00000000-0000-0000-0000-000000000000";

const PRODUCT_FIELD_ORDER = [
  "name_product",
  "latin_name",
  "size_product",
  "unit_box",
  "packages",
  "quantity",
  "weight",
  "net_weight",
  "gross_weight",
  "price_per_unit",
  "total_price",
  "currency",
];

const PRODUCT_FIELD_LABELS: Record<string, string> = {
  name_product: "Наименование",
  latin_name: "Латинское название",
  size_product: "Размер",
  unit_box: "Единица / коробка",
  packages: "Кол-во упаковок",
  quantity: "Количество",
  weight: "Вес",
  net_weight: "Нетто",
  gross_weight: "Брутто",
  price_per_unit: "Цена за единицу",
  total_price: "Сумма",
  currency: "Валюта",
};

const PRODUCT_FIELD_ORDER_MAP = new Map(PRODUCT_FIELD_ORDER.map((field, index) => [field, index]));

function confidenceColor(confidence: number | null) {
  if (confidence === null || Number.isNaN(confidence)) return "transparent";
  const clamped = Math.max(0, Math.min(confidence, 1));
  const start = [59, 130, 246];
  const end = [255, 255, 255];
  const rgb = start.map((component, index) => {
    const target = end[index];
    return Math.round(component * (1 - clamped) + target * clamped);
  });
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.35)`;
}

function productFieldOrder(field: string): number {
  const normalized = field.toLowerCase();
  const direct = PRODUCT_FIELD_ORDER_MAP.get(normalized);
  if (direct !== undefined) {
    return direct;
  }
  return PRODUCT_FIELD_ORDER.length;
}

function productFieldLabel(field: string): string {
  const normalized = field.toLowerCase();
  if (Object.prototype.hasOwnProperty.call(PRODUCT_FIELD_LABELS, normalized)) {
    return PRODUCT_FIELD_LABELS[normalized];
  }
  return field.replace(/[_\.]/g, " ");
}

function productColumnLabel(key: string): string {
  const match = key.match(/(\d+)/);
  if (match) {
    return `Продукт ${match[1]}`;
  }
  return key.replace(/_/g, " ");
}

function severityClass(severity: string): string {
  const normalized = severity.toLowerCase();
  if (normalized === "error" || normalized === "critical") {
    return "text-destructive";
  }
  if (normalized === "warn" || normalized === "warning") {
    return "text-amber-600";
  }
  return "text-muted-foreground";
}

function parseRefEntry(value: unknown): ValidationRef | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const data = value as Record<string, unknown>;
  const docIdValue = data["doc_id"];
  const docTypeValue = data["doc_type"];
  const fieldKeyValue = data["field_key"];
  const labelValue = data["label"];
  const messageValue = data["message"];
  const presentValue = data["present"];
  const noteValue = data["note"];
  const docId = typeof docIdValue === "string" ? docIdValue : undefined;
  const docType = typeof docTypeValue === "string" ? docTypeValue : undefined;
  const fieldKey = typeof fieldKeyValue === "string" ? fieldKeyValue : undefined;
  const label = typeof labelValue === "string" ? labelValue : undefined;
  const message = typeof messageValue === "string" ? messageValue : undefined;
  const present =
    typeof presentValue === "boolean"
      ? presentValue
      : docId === EMPTY_DOC_ID
        ? false
        : undefined;
  const note = typeof noteValue === "string" ? noteValue : undefined;
  return { doc_id: docId, doc_type: docType, field_key: fieldKey, label, message, present, note };
}

function parseRefs(entry: Record<string, unknown>): ValidationRef[] {
  const raw = entry?.refs;
  if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed.map(parseRefEntry).filter((item): item is ValidationRef => item !== null);
      }
      return [];
    } catch {
      return [];
    }
  }
  if (Array.isArray(raw)) {
    return raw.map(parseRefEntry).filter((item): item is ValidationRef => item !== null);
  }
  return [];
}

function SummaryTablePage() {
  const params = useParams();
  const { refresh } = useHistoryContext();

  const batchId = params.batchId;

  const [batch, setBatch] = useState<BatchDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchBatch = useCallback(async () => {
    if (!batchId) return;
    const response = await fetchBatchDetails(batchId);
    setBatch(response.batch);
    void refresh();
  }, [batchId, refresh]);

  useEffect(() => {
    let cancelled = false;
    if (!batchId) {
      setError(new Error("Не указан идентификатор пакета."));
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchBatch()
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
  }, [batchId, fetchBatch]);

  const documents = batch?.documents ?? [];
  const documentMap = useMemo(() => {
    const map = new Map<string, DocumentPayload>();
    documents.forEach((doc) => map.set(doc.id, doc));
    return map;
  }, [documents]);

  const docPresence: DocPresenceItem[] = useMemo(() => {
    if (!batch) {
      return [];
    }
    const presentByType = new Map<string, { docIds: string[]; filenames: string[] }>();
    documents.forEach((doc) => {
      const entry = presentByType.get(doc.doc_type) ?? { docIds: [], filenames: [] };
      entry.docIds.push(doc.id);
      if (doc.filename) {
        entry.filenames.push(doc.filename);
      }
      presentByType.set(doc.doc_type, entry);
    });

    const referencedTypes = new Set<string>();
    const includeDocType = (docType?: string) => {
      if (docType) {
        referencedTypes.add(docType);
      }
    };

    const validationsRaw = (batch.report?.validations ?? []) as Record<string, unknown>[];
    validationsRaw.forEach((entry) => {
      parseRefs(entry).forEach((ref) => includeDocType(ref.doc_type));
    });

    const reportDocs = (batch.report?.documents ?? []) as Record<string, unknown>[];
    reportDocs.forEach((entry) => {
      const docTypeValue = entry["doc_type"];
      if (typeof docTypeValue === "string") {
        includeDocType(docTypeValue);
      }
    });

    const relevantTypes = new Set<string>([...presentByType.keys(), ...referencedTypes]);
    const orderedTypes: string[] = [];
    (batch.doc_types ?? []).forEach((docType) => {
      if (relevantTypes.has(docType)) {
        orderedTypes.push(docType);
        relevantTypes.delete(docType);
      }
    });
    Array.from(relevantTypes)
      .sort()
      .forEach((docType) => orderedTypes.push(docType));

    return orderedTypes.map((docType) => {
      const info = presentByType.get(docType);
      return {
        docType,
        present: Boolean(info),
        filenames: info ? info.filenames : [],
        count: info ? info.docIds.length : 0,
      };
    });
  }, [batch, documents]);

  const missingDocTypes = useMemo(() => {
    const absent = docPresence.filter((item) => !item.present);
    return new Set(absent.map((item) => item.docType));
  }, [docPresence]);

  const validations: ValidationEntry[] = useMemo(() => {
    if (!batch?.report?.available) {
      return [];
    }
    const rawEntries = (batch.report.validations ?? []) as Record<string, unknown>[];
    return rawEntries
      .map((entry, index) => {
        const refs = parseRefs(entry);
        const ruleIdValue = entry["rule_id"];
        const severityValue = entry["severity"];
        const messageValue = entry["message"];
        const ruleId =
          typeof ruleIdValue === "string" && ruleIdValue.trim().length > 0 ? ruleIdValue : `rule_${index + 1}`;
        const severity = typeof severityValue === "string" ? severityValue : "info";
        const message = typeof messageValue === "string" ? messageValue : "";
        const realRefs = refs.filter((ref) => {
          if (!ref.doc_id || ref.doc_id === EMPTY_DOC_ID) {
            return false;
          }
          if (ref.present === false) {
            return false;
          }
          const doc = documentMap.get(ref.doc_id);
          if (!doc) {
            return false;
          }
          if (missingDocTypes.has(doc.doc_type)) {
            return false;
          }
          return true;
        });
        const missingRefs = refs.filter((ref) => {
          if (ref.present === false) {
            return true;
          }
          if (ref.doc_id === EMPTY_DOC_ID) {
            return true;
          }
          if (!ref.doc_id && ref.doc_type && missingDocTypes.has(ref.doc_type)) {
            return true;
          }
          return false;
        });
        if (missingRefs.length > 0 && realRefs.length <= 1) {
          return null;
        }
        return {
          ruleId,
          severity,
          message,
          refs: realRefs,
        } as ValidationEntry;
      })
      .filter((entry): entry is ValidationEntry => entry !== null);
  }, [batch, documentMap, missingDocTypes]);

  const productIssues = useMemo(() => {
    const map = new Map<string, ProductIssue[]>();
    validations.forEach((validation) => {
      validation.refs.forEach((ref) => {
        if (!ref.field_key || !ref.field_key.startsWith("products.") || !ref.doc_id) {
          return;
        }
        const segments = ref.field_key.split(".");
        if (segments.length < 3) {
          return;
        }
        const productKey = segments[1];
        const field = segments.slice(2).join(".");
        const key = `${ref.doc_id}|${productKey}|${field}`;
        const message = ref.message ?? validation.message;
        const finalMessage = ref.note ? `${message} (${ref.note})` : message;
        const existing = map.get(key) ?? [];
        if (!existing.some((item) => item.message === finalMessage && item.severity === validation.severity)) {
          existing.push({ severity: validation.severity, message: finalMessage });
        }
        map.set(key, existing);
      });
    });
    return map;
  }, [validations]);

  const productMatrix = useMemo(() => {
    if (!batch?.report?.documents) {
      return null;
    }
    const entries = (batch.report.documents ?? []) as Record<string, unknown>[];
    const columnOrder = new Map<string, number>();
    const rows = new Map<string, ProductMatrixRow>();

    entries.forEach((entry) => {
      const fieldKeyValue = entry["field_key"];
      if (typeof fieldKeyValue !== "string" || !fieldKeyValue.startsWith("products.")) {
        return;
      }
      const parts = fieldKeyValue.split(".");
      if (parts.length < 3) {
        return;
      }
      const productKey = parts[1];
      const field = parts.slice(2).join(".");
      const docIdValue = entry["doc_id"];
      const docTypeValue = entry["doc_type"];
      const filenameValue = entry["filename"];
      const valueRaw = entry["value"];
      const confidenceRaw = entry["confidence"];

      if (!columnOrder.has(productKey)) {
        const match = productKey.match(/(\d+)/);
        const order = match ? parseInt(match[1], 10) : Number.MAX_SAFE_INTEGER;
        columnOrder.set(productKey, order);
      }

      const rowKey = `${typeof docIdValue === "string" ? docIdValue : docTypeValue ?? "unknown"}::${field}`;
      const currentRow =
        rows.get(rowKey) ??
        {
          key: rowKey,
          docId: typeof docIdValue === "string" ? docIdValue : null,
          docType: typeof docTypeValue === "string" ? docTypeValue : null,
          filename: typeof filenameValue === "string" ? filenameValue : null,
          field,
          cells: {},
        };

      let value: string | null = null;
      if (typeof valueRaw === "string") {
        value = valueRaw.trim() ? valueRaw : null;
      } else if (valueRaw != null) {
        value = String(valueRaw);
      }

      let confidence: number | null = null;
      if (typeof confidenceRaw === "number" && Number.isFinite(confidenceRaw)) {
        confidence = confidenceRaw;
      } else if (typeof confidenceRaw === "string") {
        const parsed = Number(confidenceRaw);
        if (!Number.isNaN(parsed)) {
          confidence = parsed;
        }
      }

      const issuesKey =
        typeof docIdValue === "string"
          ? `${docIdValue}|${productKey}|${field}`
          : currentRow.docId
            ? `${currentRow.docId}|${productKey}|${field}`
            : null;
      const issues = issuesKey ? productIssues.get(issuesKey) ?? [] : [];

      currentRow.cells[productKey] = {
        value,
        confidence,
        issues,
      };
      rows.set(rowKey, currentRow);
    });

    if (rows.size === 0 || columnOrder.size === 0) {
      return null;
    }

    const columns = Array.from(columnOrder.entries())
      .sort((a, b) => {
        if (a[1] !== b[1]) {
          return a[1] - b[1];
        }
        return a[0].localeCompare(b[0]);
      })
      .map(([key]) => ({ key, label: productColumnLabel(key) }));

    const rowItems = Array.from(rows.values()).sort((a, b) => {
      const fieldOrder = productFieldOrder(a.field) - productFieldOrder(b.field);
      if (fieldOrder !== 0) {
        return fieldOrder;
      }
      const fieldCompare = a.field.localeCompare(b.field);
      if (fieldCompare !== 0) {
        return fieldCompare;
      }
      const docTypeA = a.docType ?? "";
      const docTypeB = b.docType ?? "";
      if (docTypeA !== docTypeB) {
        return docTypeA.localeCompare(docTypeB);
      }
      const fileA = a.filename ?? "";
      const fileB = b.filename ?? "";
      return fileA.localeCompare(fileB);
    });

    return { columns, rows: rowItems };
  }, [batch, productIssues]);

  const missingDocNames = useMemo(() => Array.from(missingDocTypes), [missingDocTypes]);

  const openEditor = (docId: string, fieldKey: string) => {
    const doc = documentMap.get(docId);
    if (!doc) return;
    const field = doc.fields.find((item) => item.field_key === fieldKey);
    const confidence =
      field && field.confidence !== null && field.confidence !== undefined ? Number(field.confidence) : null;
    setSelectedCell({
      docId,
      fieldKey,
      value: field?.value ?? null,
      confidence,
    });
  };

  const handleSave = async () => {
    if (!selectedCell) return;
    const { docId, fieldKey, value } = selectedCell;
    try {
      setSaving(true);
      const normalized = value?.trim() ? value.trim() : null;
      await updateField(docId, fieldKey, normalized);
      await confirmField(docId, fieldKey);
      await fetchBatch();
      setSelectedCell(null);
      setMessage("Поле сохранено и подтверждено");
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!batchId) {
    return <Alert variant="destructive">Не указан идентификатор пакета.</Alert>;
  }

  if (loading) {
    return (
      <div className="flex h-80 items-center justify-center text-muted-foreground">
        <Spinner className="mr-3" /> Загружаем итоговый отчёт...
      </div>
    );
  }

  if (error) {
    return <Alert variant="destructive">{error.message}</Alert>;
  }

  if (!batch) {
    return <Alert variant="info">Данные отчёта недоступны.</Alert>;
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">Итоговый отчёт</h1>
          <p className="text-muted-foreground">
            Загружен {formatPacketTimestamp(batch.created_at)} · статус: {statusLabel(mapBatchStatus(batch.status))} ·
            обновлён {formatDateTime(batch.updated_at)}
          </p>
        </div>
        {batch.links?.report_xlsx ? (
          <Button asChild variant="outline" className="self-start sm:self-end">
            <a href={batch.links.report_xlsx} target="_blank" rel="noopener noreferrer" download>
              Скачать XLSX
            </a>
          </Button>
        ) : null}
      </header>

      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Состав пакета</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {docPresence.length === 0 ? (
            <Alert variant="info">Нет информации о документах в пакете.</Alert>
          ) : (
            <>
              {missingDocNames.length > 0 ? (
                <Alert variant="warning">
                  Отсутствуют документы: {missingDocNames.join(", ")}
                </Alert>
              ) : null}
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Тип документа</TableHead>
                      <TableHead>Статус</TableHead>
                      <TableHead>Файлы</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {docPresence.map((item) => (
                      <TableRow key={item.docType}>
                        <TableCell className="font-medium">{item.docType}</TableCell>
                        <TableCell>
                          <Badge variant={item.present ? "success" : "destructive"}>
                            {item.present ? "В наличии" : "Отсутствует"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {item.filenames.length ? item.filenames.join(", ") : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Товары и проверки</CardTitle>
        </CardHeader>
        <CardContent>
          {!productMatrix ? (
            <Alert variant="info">Нет данных о товарных позициях.</Alert>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Документ / поле</TableHead>
                    {productMatrix.columns.map((column) => (
                      <TableHead key={column.key}>{column.label}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {productMatrix.rows.map((row) => (
                    <TableRow key={row.key}>
                      <TableCell className="align-top">
                        <div className="text-sm font-medium">{row.docType ?? "—"}</div>
                        <div className="text-xs text-muted-foreground">{productFieldLabel(row.field)}</div>
                        {row.filename ? (
                          <div className="text-xs text-muted-foreground">{row.filename}</div>
                        ) : null}
                      </TableCell>
                      {productMatrix.columns.map((column) => {
                        const cell = row.cells[column.key];
                        const background = cell?.confidence != null ? confidenceColor(cell.confidence) : "transparent";
                        return (
                          <TableCell
                            key={`${row.key}-${column.key}`}
                            className="align-top text-sm"
                            style={{ backgroundColor: background }}
                          >
                            <div>{cell?.value ?? "—"}</div>
                            {cell?.confidence != null ? (
                              <div className="text-xs text-muted-foreground">({cell.confidence.toFixed(2)})</div>
                            ) : null}
                            {cell?.issues.length ? (
                              <ul className="mt-2 space-y-1">
                                {cell.issues.map((issue, index) => (
                                  <li key={index} className={cn("text-xs", severityClass(issue.severity))}>
                                    {issue.message}
                                  </li>
                                ))}
                              </ul>
                            ) : null}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Правила и замечания</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {!batch.report.available ? (
            <Alert variant="info">Отчёт ещё формируется.</Alert>
          ) : validations.length === 0 ? (
            <Alert variant="success">Нарушений не обнаружено.</Alert>
          ) : (
            validations.map((validation) => (
              <div key={validation.ruleId} className="rounded-2xl border border-muted bg-muted/10 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold">{validation.ruleId}</p>
                    <p className="text-sm text-muted-foreground">{validation.message}</p>
                  </div>
                  <Badge variant="destructive">{validation.severity}</Badge>
                </div>
                <div className="mt-3 overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Документ</TableHead>
                        <TableHead>Поле</TableHead>
                        <TableHead>Значение</TableHead>
                        <TableHead>Комментарий</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {validation.refs.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={5} className="text-sm text-muted-foreground">
                            Подробности отсутствуют.
                          </TableCell>
                        </TableRow>
                      ) : (
                        validation.refs.map((ref, index) => {
                          const doc = ref.doc_id ? documentMap.get(ref.doc_id) : undefined;
                          const field: FieldState | undefined = doc?.fields.find(
                            (item) => item.field_key === ref.field_key,
                          );
                          const confidence =
                            field && field.confidence !== null && field.confidence !== undefined
                              ? Number(field.confidence)
                              : null;
                          const preview = doc?.previews[0];
                          return (
                            <TableRow key={`${validation.ruleId}-${index}`}>
                              <TableCell className="align-top">
                                {doc ? (
                                  <div>
                                    <p className="text-sm font-medium">{doc.filename}</p>
                                    <p className="text-xs text-muted-foreground">{doc.doc_type}</p>
                                  </div>
                                ) : (
                                  <span className="text-sm text-muted-foreground">—</span>
                                )}
                              </TableCell>
                              <TableCell className="align-top text-sm">{ref.field_key ?? "—"}</TableCell>
                              <TableCell
                                className={cn("align-top text-sm", preview && "group relative")}
                                style={{ backgroundColor: confidenceColor(confidence) }}
                              >
                                <div>{field?.value ?? "—"}</div>
                                {preview ? (
                                  <div className="pointer-events-none absolute left-full top-1/2 hidden -translate-y-1/2 translate-x-3 rounded-xl border bg-background shadow-xl group-hover:block">
                                    <img src={preview} alt="" className="max-h-48 rounded-xl" />
                                  </div>
                                ) : null}
                              </TableCell>
                              <TableCell className="align-top text-sm text-muted-foreground">
                                {ref.message ?? ref.label ?? validation.message}
                              </TableCell>
                              <TableCell className="align-top">
                                {doc && ref.field_key ? (
                                  <Button size="sm" variant="outline" onClick={() => openEditor(doc.id, ref.field_key!)}>
                                    Открыть
                                  </Button>
                                ) : null}
                              </TableCell>
                            </TableRow>
                          );
                        })
                      )}
                    </TableBody>
                  </Table>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {selectedCell ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-3xl border bg-background p-6 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">Редактирование поля</h2>
                <p className="text-sm text-muted-foreground">
                  Поле: {selectedCell.fieldKey} · уверенность: {" "}
                  {selectedCell.confidence !== null ? selectedCell.confidence.toFixed(2) : "—"}
                </p>
              </div>
              <Button variant="ghost" onClick={() => setSelectedCell(null)} disabled={saving}>
                Закрыть
              </Button>
            </div>
            <div className="mt-4 space-y-4">
              {(selectedCell.value ?? "").length > 80 ? (
                <Textarea
                  rows={6}
                  value={selectedCell.value ?? ""}
                  onChange={(event) =>
                    setSelectedCell((prev) => (prev ? { ...prev, value: event.target.value } : prev))
                  }
                />
              ) : (
                <Input
                  value={selectedCell.value ?? ""}
                  onChange={(event) =>
                    setSelectedCell((prev) => (prev ? { ...prev, value: event.target.value } : prev))
                  }
                />
              )}
            </div>
            <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
              <Button variant="ghost" onClick={() => setSelectedCell(null)} disabled={saving}>
                Отмена
              </Button>
              <Button onClick={() => void handleSave()} disabled={saving}>
                сохранить
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default SummaryTablePage;
