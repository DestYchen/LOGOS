import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

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

function parseRefs(entry: Record<string, unknown>): ValidationRef[] {
  const raw = entry?.refs;
  if (typeof raw === "string" && raw.trim()) {
    try {
      return JSON.parse(raw) as ValidationRef[];
    } catch {
      return [];
    }
  }
  if (Array.isArray(raw)) {
    return raw as ValidationRef[];
  }
  return [];
}

function SummaryTablePage() {
  const params = useParams();
  const navigate = useNavigate();
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

  const validations: ValidationEntry[] = useMemo(() => {
    if (!batch?.report.validation_matrix) {
      return [];
    }
    const raw = (batch.report.validations ?? []) as Record<string, unknown>[];
    const mapped = batch.report.validation_matrix.map((row: Record<string, unknown>, index: number) => {
      const base = raw[index] ?? {};
      const refs = parseRefs(base);
      return {
        ruleId: String(row.rule_id ?? base.rule_id ?? "Правило"),
        severity: String(row.severity ?? base.severity ?? "info"),
        message: String(row.message ?? base.message ?? ""),
        refs,
      };
    });
    return mapped.filter((entry) => entry.refs.some((ref) => ref.doc_id));
  }, [batch]);

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

  const handleSave = async (confirmAfterSave: boolean) => {
    if (!selectedCell) return;
    const { docId, fieldKey, value } = selectedCell;
    try {
      setSaving(true);
      await updateField(docId, fieldKey, value?.trim() ? value.trim() : null);
      if (confirmAfterSave) {
        await confirmField(docId, fieldKey);
      }
      await fetchBatch();
      setSelectedCell(null);
      setMessage(confirmAfterSave ? "Поле сохранено и подтверждено" : "Поле сохранено");
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
        <Spinner className="mr-3" /> Загрузка итоговой таблицы...
      </div>
    );
  }

  if (error) {
    return <Alert variant="destructive">{error.message}</Alert>;
  }

  if (!batch) {
    return <Alert variant="info">Пакет недоступен.</Alert>;
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">Итоговая таблица</h1>
          <p className="text-muted-foreground">
            Пакет {formatPacketTimestamp(batch.created_at)} · Статус: {statusLabel(mapBatchStatus(batch.status))} · Обновлён{" "}
            {formatDateTime(batch.updated_at)}
          </p>
        </div>
        {batch.links?.report_xlsx ? (
          <Button asChild variant="outline" className="self-start sm:self-end">
            <a href={batch.links.report_xlsx} target="_blank" rel="noopener noreferrer" download>
              Экспорт в XLSX
            </a>
          </Button>
        ) : null}
      </header>

      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <Card className="rounded-3xl border bg-background">
        <CardHeader>
          <CardTitle>Ошибки и предупреждения</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {!batch.report.available ? (
            <Alert variant="info">Итоговый отчёт ещё не готов.</Alert>
          ) : validations.length === 0 ? (
            <Alert variant="success">Ошибок не обнаружено.</Alert>
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
                            Нет детализированных ссылок.
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
                                  <span className="text-sm text-muted-foreground">Неизвестно</span>
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
                                    Исправить
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
                  Поле: {selectedCell.fieldKey} · Уверенность:{" "}
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
              <Button onClick={() => void handleSave(false)} disabled={saving}>
                Сохранить
              </Button>
              <Button variant="secondary" onClick={() => void handleSave(true)} disabled={saving}>
                Сохранить и подтвердить
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default SummaryTablePage;
