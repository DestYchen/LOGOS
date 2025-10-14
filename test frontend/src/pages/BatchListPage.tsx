import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Spinner } from "../components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { deleteBatch, fetchBatches } from "../lib/api";
import { formatDateTime } from "../lib/utils";
import { useAsync } from "../hooks/useAsync";
import type { BatchSummary } from "../types/api";

function statusVariant(status: string) {
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

function BatchListPage() {
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);

  const { loading, error, data, reload } = useAsync(fetchBatches, []);

  const batches = data?.batches ?? [];

  const handleDelete = async (batch: BatchSummary) => {
    setActionError(null);
    setMessage(null);
    setWorkingId(batch.id);
    try {
      await deleteBatch(batch.id);
      setMessage(`Batch ${batch.id} deleted.`);
      await reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setWorkingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Batches</h1>
          <p className="text-muted-foreground">Track processing progress, re-open batches or remove unused ones.</p>
        </div>
        <Button variant="secondary" onClick={() => reload()} disabled={loading}>
          Refresh
        </Button>
      </div>

      <div className="space-y-3">
        {message ? <Alert variant="success">{message}</Alert> : null}
        {actionError ? <Alert variant="destructive">{actionError}</Alert> : null}
        {error ? <Alert variant="destructive">{error.message}</Alert> : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent batches</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex h-32 items-center justify-center text-muted-foreground">
              <Spinner className="mr-3" />
              Loading batches...
            </div>
          ) : batches.length === 0 ? (
            <p className="text-sm text-muted-foreground">No batches yet. Upload documents to create a new batch.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[220px]">Batch ID</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Documents</TableHead>
                  <TableHead>Created at</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {batches.map((batch) => (
                  <TableRow key={batch.id}>
                    <TableCell>
                      <Link to={`/batches/${batch.id}`} className="font-medium text-primary underline-offset-2 hover:underline">
                        {batch.id}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(batch.status)}>{batch.status}</Badge>
                    </TableCell>
                    <TableCell>{batch.documents_count}</TableCell>
                    <TableCell>{formatDateTime(batch.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <Button asChild variant="link">
                        <Link to={`/batches/${batch.id}`}>Open</Link>
                      </Button>
                      <Button
                        variant="ghost"
                        className="text-destructive"
                        disabled={!batch.can_delete || workingId === batch.id}
                        onClick={() => handleDelete(batch)}
                      >
                        {workingId === batch.id ? "Deleting..." : "Delete"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default BatchListPage;
