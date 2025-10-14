import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Spinner } from "../components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Textarea } from "../components/ui/textarea";
import { confirmField, deleteDocument, fetchBatchDetails, refillDocument, setDocumentType, updateField, completeBatch } from "../lib/api";
import { formatDateTime } from "../lib/utils";
import { useAsync } from "../hooks/useAsync";
import type { BatchDetails, DocumentPayload, FieldState, ProductTable } from "../types/api";

type PendingState = Record<string, boolean>;

function usePendingActions() {
  const [pending, setPending] = useState<PendingState>({});

  const set = useCallback((key: string, value: boolean) => {
    setPending((previous) => {
      if (previous[key] === value) {
        return previous;
      }
      const next = { ...previous };
      if (value) {
        next[key] = true;
      } else {
        delete next[key];
      }
      return next;
    });
  }, []);

  const isPending = useCallback((key: string) => Boolean(pending[key]), [pending]);

  return { set, isPending };
}

function statusBadgeVariant(status: string) {
  switch (status) {
    case "DONE":
    case "VALIDATED":
      return "success";
    case "FAILED":
      return "destructive";
    case "FILLED_REVIEWED":
    case "FILLED_AUTO":
      return "secondary";
    default:
      return "outline";
  }
}

function reasonLabel(reason: string) {
  switch (reason) {
    case "missing":
      return "Missing";
    case "low_confidence":
      return "Low confidence";
    case "unknown_type":
      return "Document type unknown";
    case "extra":
      return "Extra field";
    default:
      return reason;
  }
}

type FieldRowProps = {
  field: FieldState;
  draftValue: string;
  onChange: (value: string) => void;
  onSave: () => void;
  onConfirm: () => void;
  saving: boolean;
  confirming: boolean;
};

function FieldRow({ field, draftValue, onChange, onSave, onConfirm, saving, confirming }: FieldRowProps) {
  return (
    <TableRow className={field.needs_confirmation ? "bg-amber-50" : undefined}>
      <TableCell className="font-mono text-xs">{field.field_key}</TableCell>
      <TableCell className="w-[280px]">
        {field.editable ? (
          <Input value={draftValue} onChange={(event) => onChange(event.target.value)} disabled={saving} />
        ) : (
          <span>{field.value ?? "—"}</span>
        )}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">{field.confidence_display ?? "—"}</TableCell>
      <TableCell>{field.required ? <Badge variant="outline">Required</Badge> : <span className="text-muted-foreground">Optional</span>}</TableCell>
      <TableCell>
        <Badge variant={field.needs_confirmation ? "warning" : "outline"}>{reasonLabel(field.reason)}</Badge>
      </TableCell>
      <TableCell className="space-x-2">
        {field.editable ? (
          <Button size="sm" variant="secondary" disabled={saving} onClick={() => { void onSave(); }}>
            {saving ? "Saving..." : "Save"}
          </Button>
        ) : null}
        {field.needs_confirmation ? (
          <Button size="sm" variant="outline" disabled={confirming} onClick={() => { void onConfirm(); }}>
            {confirming ? "Confirming..." : "Confirm"}
          </Button>
        ) : null}
      </TableCell>
    </TableRow>
  );
}

type ProductTableViewProps = {
  table: ProductTable;
};

function ProductTableView({ table }: ProductTableViewProps) {
  if (!table.columns.length || !table.rows.length) {
    return <p className="text-sm text-muted-foreground">No product-level data available.</p>;
  }

  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow>
          {table.columns.map((column) => (
            <TableHead key={column.key}>{column.label}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {table.rows.map((row) => (
          <TableRow key={row.key}>
            {table.columns.map((column) => {
              const cell = row.cells[column.key];
              return (
                <TableCell key={column.key}>
                  <div>{cell?.value ?? "—"}</div>
                  {cell?.confidence_display ? (
                    <div className="text-[10px] text-muted-foreground">Confidence {cell.confidence_display}</div>
                  ) : null}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

type DocumentCardProps = {
  document: DocumentPayload;
  docTypes: string[];
  isPending: (key: string) => boolean;
  onSaveField: (docId: string, fieldKey: string, value: string | null) => Promise<void>;
  onConfirmField: (docId: string, fieldKey: string) => Promise<void>;
  onSetType: (docId: string, docType: string) => Promise<void>;
  onRefill: (docId: string) => Promise<void>;
  onDelete: (docId: string) => Promise<void>;
};

function DocumentCard({
  document,
  docTypes,
  isPending,
  onSaveField,
  onConfirmField,
  onSetType,
  onRefill,
  onDelete,
}: DocumentCardProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    document.fields.forEach((field) => {
      initial[field.field_key] = field.value ?? "";
    });
    return initial;
  });

  useEffect(() => {
    const next: Record<string, string> = {};
    document.fields.forEach((field) => {
      next[field.field_key] = field.value ?? "";
    });
    setDrafts(next);
  }, [document.fields]);

  const handleSaveField = async (field: FieldState) => {
    const value = drafts[field.field_key]?.trim() ?? "";
    await onSaveField(document.id, field.field_key, value === "" ? null : value);
  };

  return (
    <Card key={document.id}>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-lg">{document.filename}</CardTitle>
            <CardDescription>
              <Badge variant={statusBadgeVariant(document.status)} className="mr-2">
                {document.status}
              </Badge>
              {document.processing ? "Processing…" : "Ready"}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={isPending(`doc:${document.id}:refill`)}
              onClick={() => {
                void onRefill(document.id);
              }}
            >
              {isPending(`doc:${document.id}:refill`) ? "Refilling..." : "Refill"}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={isPending(`doc:${document.id}:delete`)}
              onClick={() => {
                void onDelete(document.id);
              }}
            >
              {isPending(`doc:${document.id}:delete`) ? "Deleting..." : "Delete"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>Document type</Label>
            <Select
              defaultValue={document.doc_type}
              onValueChange={(value) => {
                if (value !== document.doc_type) {
                  void onSetType(document.id, value);
                }
              }}
              disabled={isPending(`doc:${document.id}:set_type`)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Choose type" />
              </SelectTrigger>
              <SelectContent>
                {docTypes.map((docType) => (
                  <SelectItem key={docType} value={docType}>
                    {docType}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Pending fields</Label>
            <p className="text-sm text-muted-foreground">
              {document.pending_count} field{document.pending_count === 1 ? "" : "s"} require review.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">Extracted fields</h3>
          </div>
          <Table className="text-sm">
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Required</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {document.fields.map((field) => (
                <FieldRow
                  key={field.field_key}
                  field={field}
                  draftValue={drafts[field.field_key] ?? ""}
                  onChange={(value) => setDrafts((prev) => ({ ...prev, [field.field_key]: value }))}
                  onSave={() => handleSaveField(field)}
                  onConfirm={() => onConfirmField(document.id, field.field_key)}
                  saving={isPending(`field:${document.id}:${field.field_key}:save`)}
                  confirming={isPending(`field:${document.id}:${field.field_key}:confirm`)}
                />
              ))}
            </TableBody>
          </Table>
        </div>

        <Tabs defaultValue="products" className="space-y-3">
          <TabsList>
            <TabsTrigger value="products">Products</TabsTrigger>
            <TabsTrigger value="json">Raw JSON</TabsTrigger>
            <TabsTrigger value="previews">Previews</TabsTrigger>
          </TabsList>
          <TabsContent value="products">
            <ProductTableView table={document.products} />
          </TabsContent>
          <TabsContent value="json">
            {document.filled_json ? (
              <Textarea value={document.filled_json} rows={12} readOnly className="font-mono text-xs" />
            ) : (
              <p className="text-sm text-muted-foreground">JSON payload will appear once processing is complete.</p>
            )}
          </TabsContent>
          <TabsContent value="previews">
            {document.previews.length ? (
              <div className="flex flex-wrap gap-4">
                {document.previews.map((url) => (
                  <img key={url} src={url} alt="Document preview" className="h-auto max-h-[480px] rounded border shadow-sm" />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No preview images generated.</p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function BatchView({ batch, refresh, setMessage, setActionError }: { batch: BatchDetails; refresh: () => Promise<void>; setMessage: (value: string) => void; setActionError: (value: string | null) => void }) {
  const { set: setPending, isPending } = usePendingActions();

  const runAction = useCallback(
    async (key: string, fn: () => Promise<{ message: string }>) => {
      setActionError(null);
      setPending(key, true);
      try {
        const result = await fn();
        setMessage(result.message || "Operation completed");
        await refresh();
      } catch (err) {
        setActionError((err as Error).message);
      } finally {
        setPending(key, false);
      }
    },
    [refresh, setActionError, setMessage, setPending],
  );

  const handleSaveField = (docId: string, fieldKey: string, value: string | null) =>
    runAction(`field:${docId}:${fieldKey}:save`, () => updateField(docId, fieldKey, value));

  const handleConfirmField = (docId: string, fieldKey: string) =>
    runAction(`field:${docId}:${fieldKey}:confirm`, () => confirmField(docId, fieldKey));

  const handleSetType = (docId: string, docType: string) =>
    runAction(`doc:${docId}:set_type`, () => setDocumentType(docId, docType));

  const handleRefill = (docId: string) => runAction(`doc:${docId}:refill`, () => refillDocument(docId));

  const handleDelete = (docId: string) => runAction(`doc:${docId}:delete`, () => deleteDocument(docId));

  const handleComplete = () => runAction(`batch:${batch.id}:complete`, () => completeBatch(batch.id));

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Batch {batch.id}</CardTitle>
          <CardDescription>
            Created {formatDateTime(batch.created_at)} · Updated {formatDateTime(batch.updated_at)}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Badge variant={statusBadgeVariant(batch.status)}>{batch.status}</Badge>
            <Badge variant="outline">{batch.documents_count} documents</Badge>
            <Badge variant="outline">{batch.pending_total} pending fields</Badge>
          </div>

          {batch.processing_warnings.length ? (
            <Alert variant="warning" className="space-y-1">
              <div className="font-semibold">Processing warnings</div>
              <ul className="list-disc pl-5 text-sm">
                {batch.processing_warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleComplete} disabled={!batch.can_complete || isPending(`batch:${batch.id}:complete`)}>
              {isPending(`batch:${batch.id}:complete`) ? "Completing..." : "Mark validation ready"}
            </Button>
            {batch.links.report_xlsx ? (
              <Button asChild variant="secondary">
                <a href={batch.links.report_xlsx}>Download Excel report</a>
              </Button>
            ) : null}
            <Button asChild variant="outline">
              <Link to="/batches">Back to list</Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-6">
        {batch.documents.map((document) => (
          <DocumentCard
            key={document.id}
            document={document}
            docTypes={batch.doc_types}
            isPending={isPending}
            onSaveField={handleSaveField}
            onConfirmField={handleConfirmField}
            onSetType={handleSetType}
            onRefill={handleRefill}
            onDelete={handleDelete}
          />
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Validation report</CardTitle>
          <CardDescription>Structured summary of detections and rules.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {batch.report.available ? (
            <>
              <div>
                <h3 className="text-sm font-medium">Validation rules</h3>
                {batch.report.validation_matrix.length ? (
                  <Table className="text-xs">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Rule</TableHead>
                        <TableHead>Severity</TableHead>
                        <TableHead>Message</TableHead>
                        {batch.report.validation_matrix_columns.map((column) => (
                          <TableHead key={column.key}>{column.label}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {batch.report.validation_matrix.map((row, index) => (
                        <TableRow key={`${row.rule_id}-${index}`}>
                          <TableCell>{row.rule_id as string}</TableCell>
                          <TableCell>{row.severity as string}</TableCell>
                          <TableCell>{row.message as string}</TableCell>
                          {batch.report.validation_matrix_columns.map((column) => (
                            <TableCell key={column.key}>
                              {(row.cells?.[column.key] as string | null) ?? "—"}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-sm text-muted-foreground">No validation issues reported.</p>
                )}
              </div>

              <div>
                <h3 className="text-sm font-medium">Raw JSON</h3>
                {batch.report.raw_json ? (
                  <Textarea value={batch.report.raw_json} readOnly rows={16} className="font-mono text-xs" />
                ) : (
                  <p className="text-sm text-muted-foreground">Report JSON is not available yet.</p>
                )}
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Report not generated yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function BatchDetailPage() {
  const params = useParams();
  const batchId = params.batchId;
  const [message, setMessage] = useState<string>("");
  const [actionError, setActionError] = useState<string | null>(null);

  const fetcher = useCallback(() => {
    if (!batchId) {
      return Promise.reject(new Error("Batch id is missing"));
    }
    return fetchBatchDetails(batchId);
  }, [batchId]);

  const { data, loading, error, reload } = useAsync(fetcher, [fetcher]);

  if (!batchId) {
    return <Alert variant="destructive">Batch id is not specified.</Alert>;
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        <Spinner className="mr-3" />
        Loading batch {batchId}...
      </div>
    );
  }

  if (error || !data) {
    return <Alert variant="destructive">{error ? error.message : "Failed to load batch"}</Alert>;
  }

  const refresh = async () => {
    await reload();
  };

  return (
    <div className="space-y-6">
      {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
      {message ? <Alert variant="success">{message}</Alert> : null}
      <BatchView batch={data.batch} refresh={refresh} setMessage={setMessage} setActionError={setActionError} />
    </div>
  );
}

export default BatchDetailPage;
