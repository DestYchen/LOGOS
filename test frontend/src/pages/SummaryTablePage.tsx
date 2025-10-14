import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Spinner } from "../components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Textarea } from "../components/ui/textarea";
import { useHistoryContext } from "../contexts/history-context";
import { confirmField, fetchBatchDetails, updateField } from "../lib/api";
import { cn, formatDateTime, mapBatchStatus, statusLabel } from "../lib/utils";
import type { BatchDetails, DocumentPayload, FieldState } from "../types/api";

type CellRef = {
  docId: string;
  fieldKey: string;
  value: string | null;
  confidence: number | null;
};

function confidenceColor(confidence: number | null) {
  if (confidence === null || Number.isNaN(confidence)) return "transparent";
  const clamped = Math.max(0, Math.min(1, confidence));
  const start = [59, 130, 246];
  const end = [255, 255, 255];
  const rgb = start.map((component, index) => {
    const target = end[index];
    return Math.round(component * (1 - clamped) + target * clamped);
  });
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.35)`;
}

function buildFieldMatrix(documents: DocumentPayload[]) {
  const fieldSet = new Set<string>();
  documents.forEach((doc) => {
    doc.fields.forEach((field) => {
      fieldSet.add(field.field_key);
    });
  });
  const columns = Array.from(fieldSet);
  const rows = documents.map((doc) => ({ doc, fields: doc.fields.reduce<Record<string, FieldState>>((acc, field) => {
    acc[field.field_key] = field;
    return acc;
  }, {}) }));
  return { columns, rows };
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
  const [selectedCell, setSelectedCell] = useState<CellRef | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!batchId) return;
    let active = true;
    setLoading(true);
    setError(null);
    fetchBatchDetails(batchId)
      .then((response) => {
        if (!active) return;
        setBatch(response.batch);
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
  }, [batchId, refresh]);

  const documents = batch?.documents ?? [];
  const matrix = useMemo(() => buildFieldMatrix(documents), [documents]);

  const handleCellSave = useCallback(
    async (ref: CellRef, nextValue: string | null, confirmAfterSave: boolean) => {
      if (!ref.docId) return;
      try {
        setSaving(true);
        await updateField(ref.docId, ref.fieldKey, nextValue);
        if (confirmAfterSave) {
          await confirmField(ref.docId, ref.fieldKey);
        }
        setMessage("Изменения сохранены");
        setSelectedCell(null);
        if (!batchId) return;
        const response = await fetchBatchDetails(batchId);
        setBatch(response.batch);
      } catch (err) {
        setActionError((err as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [batchId],
  );

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

  if (error || !batch) {
    return <Alert variant="destructive">{error ? error.message : "Пакет не найден"}</Alert>;
  }

  const mistakes = batch.report.validation_matrix;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Итоговая таблица</h1>
          <p className="text-muted-foreground">
            Пакет {batch.id.slice(0, 8)} • Статус: {statusLabel(mapBatchStatus(batch.status))} • Обновлён {formatDateTime(batch.updated_at)}
          </p>
        </div>
        <div className="space-x-2">
          {batch.links.report_xlsx ? (
            <Button variant="secondary" asChild>
              <a href={batch.links.report_xlsx} target="_blank" rel="noopener noreferrer">
                Экспортировать отчёт
              </a>
            </Button>
          ) : (
            <Button variant="secondary" disabled>
              Экспортировать отчёт
            </Button>
          )}
          <Button variant="ghost" asChild>
            <Link to={`/resolve/${batch.id}`}>Документ — исправление ошибок</Link>
          </Button>
        </div>
      </header>

      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}

      <Card className="rounded-3xl border bg-background/95">
        <CardHeader>
          <CardTitle>Данные по документам</CardTitle>
          <CardDescription>Нажмите на ячейку, чтобы исправить значение или подтвердить поле.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 z-10 bg-background">Документ</TableHead>
                {matrix.columns.map((column) => (
                  <TableHead key={column}>{column}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {matrix.rows.map(({ doc, fields }) => (
                <TableRow key={doc.id}>
                  <TableCell className="sticky left-0 z-10 bg-background font-medium">
                    <div className="flex flex-col">
                      <span className="truncate" title={doc.filename}>
                        {doc.filename}
                      </span>
                      <span className="text-xs text-muted-foreground">{doc.doc_type}</span>
                    </div>
                  </TableCell>
                  {matrix.columns.map((column) => {
                    const field = fields[column];
                    const confidence = field?.confidence ?? null;
                    const background = confidenceColor(confidence);
                    return (
                      <TableCell key={column} className="align-top">
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedCell({
                              docId: doc.id,
                              fieldKey: column,
                              value: field?.value ?? null,
                              confidence,
                            })
                          }
                          className="group relative w-full text-left"
                          style={{ backgroundColor: background }}
                        >
                          <div className="min-h-[48px] whitespace-pre-wrap text-sm">
                            {field?.value ?? "—"}
                          </div>
                          {doc.previews.length ? (
                            <div className="pointer-events-none absolute left-full top-1/2 z-20 hidden -translate-y-1/2 translate-x-3 rounded-xl border bg-background shadow-xl group-hover:block">
                              <img src={doc.previews[0]} alt="Превью" className="max-h-[220px] w-auto rounded-xl" />
                            </div>
                          ) : null}
                        </button>
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {documents.some((doc) => doc.products.rows.length) ? (
        <Card className="rounded-3xl border bg-background/95">
          <CardHeader>
            <CardTitle>Товарные позиции</CardTitle>
            <CardDescription>Структурированные данные по позициям внутри документов.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {documents.map((doc) => (
              doc.products.rows.length ? (
                <div key={doc.id} className="space-y-3">
                  <h3 className="text-sm font-medium">{doc.filename}</h3>
                  <div className="overflow-auto rounded-xl border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/30">
                        <tr>
                          {doc.products.columns.map((column) => (
                            <th key={column.key} className="px-3 py-2 text-left font-medium">
                              {column.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {doc.products.rows.map((row) => (
                          <tr key={row.key} className="border-t">
                            {doc.products.columns.map((column) => {
                              const cell = row.cells[column.key];
                              const background = confidenceColor(cell?.confidence ?? null);
                              return (
                                <td key={column.key} className="px-3 py-2" style={{ backgroundColor: background }}>
                                  <div>{cell?.value ?? "—"}</div>
                                  {cell?.confidence_display ? (
                                    <div className="text-xs text-muted-foreground">{cell.confidence_display}</div>
                                  ) : null}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Card className="rounded-3xl border bg-background/95">
        <CardHeader>
          <CardTitle>Ошибки и предупреждения</CardTitle>
          <CardDescription>Правила проверки, которые необходимо устранить.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {mistakes.length ? (
            mistakes.map((row, index) => (
              <div key={`${row.rule_id}-${index}`} className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-sm font-medium">{row.rule_id as string}</span>
                  <Badge variant="destructive">{row.severity as string}</Badge>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{row.message as string}</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {Object.entries(row.cells ?? {}).map(([key, value]) => (
                    value ? (
                      <div key={key} className="rounded-lg bg-background px-3 py-2 text-xs text-muted-foreground">
                        <strong className="text-foreground">{key}:</strong>
                        <span className="ml-2 whitespace-pre-wrap">{value as string}</span>
                      </div>
                    ) : null
                  ))}
                </div>
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">Ошибки по правилам не обнаружены.</p>
          )}
        </CardContent>
      </Card>

      {selectedCell ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-3xl border bg-background p-6 shadow-xl">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-lg font-semibold">Редактирование поля</h2>
                <p className="text-sm text-muted-foreground">
                  Поле: {selectedCell.fieldKey} • Уверенность: {selectedCell.confidence ?? "—"}
                </p>
              </div>
              <Button variant="ghost" onClick={() => setSelectedCell(null)}>
                Закрыть
              </Button>
            </div>
            <div className="mt-4 space-y-4">
              {(selectedCell.value ?? "").length > 80 ? (
                <Textarea
                  rows={6}
                  value={selectedCell.value ?? ""}
                  onChange={(event) => setSelectedCell({ ...selectedCell, value: event.target.value })}
                />
              ) : (
                <Input
                  value={selectedCell.value ?? ""}
                  onChange={(event) => setSelectedCell({ ...selectedCell, value: event.target.value })}
                />
              )}
            </div>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <Button
                variant="secondary"
                onClick={() => setSelectedCell(selectedCell ? { ...selectedCell, value: null } : null)}
              >
                Очистить
              </Button>
              <div className="space-x-2">
                <Button
                  variant="ghost"
                  onClick={() => setSelectedCell(null)}
                  disabled={saving}
                >
                  Отмена
                </Button>
                <Button
                  onClick={() =>
                    selectedCell &&
                    handleCellSave(selectedCell, selectedCell.value ?? null, false)
                  }
                  disabled={saving}
                >
                  Сохранить
                </Button>
                <Button
                  variant="secondary"
                  onClick={() =>
                    selectedCell &&
                    handleCellSave(selectedCell, selectedCell.value ?? null, true)
                  }
                  disabled={saving}
                >
                  Сохранить и подтвердить
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <Card className="rounded-3xl border bg-background/95">
        <CardHeader>
          <CardTitle>Следующие шаги</CardTitle>
          <CardDescription>После подтверждения всех полей можно закрыть пакет.</CardDescription>
        </CardHeader>
        <CardFooter className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="secondary" asChild>
            <Link to="/history">История</Link>
          </Button>
          <Button variant="default" onClick={() => navigate("/new")}>Новый пакет</Button>
        </CardFooter>
      </Card>
    </div>
  );
}

export default SummaryTablePage;
