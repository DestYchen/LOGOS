import { useState } from "react";

import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Alert } from "../components/ui/alert";
import { Spinner } from "../components/ui/spinner";
import { uploadDocuments } from "../lib/api";

type UploadResult = {
  batchId: string;
  documents: number;
};

function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const newFiles = event.target.files ? Array.from(event.target.files) : [];
    setFiles(newFiles);
    setResult(null);
    setError(null);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!files.length) {
      setError("Please select at least one file to upload.");
      return;
    }
    try {
      setUploading(true);
      setError(null);
      const response = await uploadDocuments(files);
      setResult({ batchId: response.batch_id, documents: response.documents });
      setFiles([]);
      event.currentTarget.reset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Upload documents</h1>
        <p className="text-muted-foreground">Select multiple PDF, DOCX, XLSX or TXT files and send them for processing.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Upload a batch</CardTitle>
          <CardDescription>The backend will automatically split multi-page PDFs and queue processing.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="files">Documents</Label>
              <Input id="files" type="file" multiple required onChange={onFileChange} disabled={uploading} />
              <p className="text-xs text-muted-foreground">
                Supported formats: PDF, DOCX, XLSX, TXT. Files are routed to OCR and JSON fillers.
              </p>
            </div>

            {files.length > 0 && (
              <p className="text-sm text-muted-foreground">{files.length} file(s) ready for upload.</p>
            )}

            <Button type="submit" disabled={uploading}>
              {uploading ? (
                <>
                  <Spinner className="mr-2" size="sm" /> Uploading…
                </>
              ) : (
                "Upload"
              )}
            </Button>
          </form>

          <div className="mt-4 space-y-3">
            {error ? <Alert variant="destructive">{error}</Alert> : null}
            {result ? (
              <Alert variant="success">
                Uploaded {result.documents} document(s).{" "}
                <a className="underline" href={`/batches/${result.batchId}`}>
                  Open batch {result.batchId}
                </a>
              </Alert>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default UploadPage;
