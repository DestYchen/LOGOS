import {
  type ApiMessageResponse,
  type BatchDetailsResponse,
  type BatchesResponse,
  type UploadResponse,
} from "../types/api";
import { API_BASE, API_JSON_BASE } from "./utils";

async function parseError(response: Response): Promise<Error> {
  let message = `${response.status} ${response.statusText}`;
  try {
    const payload = await response.json();
    if (payload && typeof payload.detail === "string") {
      message = payload.detail;
    }
  } catch {
    // ignored
  }
  return new Error(message);
}

async function request<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as T;
}

export async function uploadDocuments(files: File[]): Promise<UploadResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return request<UploadResponse>(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });
}

export async function fetchBatches(): Promise<BatchesResponse> {
  return request<BatchesResponse>(`${API_JSON_BASE}/batches`);
}

export async function fetchBatchDetails(batchId: string): Promise<BatchDetailsResponse> {
  return request<BatchDetailsResponse>(`${API_JSON_BASE}/batches/${batchId}`);
}

export async function completeBatch(batchId: string): Promise<ApiMessageResponse> {
  return request<ApiMessageResponse>(`${API_JSON_BASE}/batches/${batchId}/complete`, {
    method: "POST",
  });
}

export async function deleteBatch(batchId: string): Promise<ApiMessageResponse> {
  return request<ApiMessageResponse>(`${API_JSON_BASE}/batches/${batchId}/delete`, {
    method: "POST",
  });
}

export async function updateField(
  docId: string,
  fieldKey: string,
  value: string | null,
): Promise<ApiMessageResponse> {
  return request<ApiMessageResponse>(`${API_JSON_BASE}/documents/${docId}/fields/${fieldKey}/update`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ value }),
  });
}

export async function confirmField(docId: string, fieldKey: string): Promise<ApiMessageResponse> {
  return request<ApiMessageResponse>(`${API_JSON_BASE}/documents/${docId}/fields/${fieldKey}/confirm`, {
    method: "POST",
  });
}

export async function setDocumentType(docId: string, docType: string): Promise<ApiMessageResponse> {
  return request<ApiMessageResponse>(`${API_JSON_BASE}/documents/${docId}/set_type`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ doc_type: docType }),
  });
}

export async function refillDocument(docId: string): Promise<ApiMessageResponse> {
  return request<ApiMessageResponse>(`${API_JSON_BASE}/documents/${docId}/refill`, {
    method: "POST",
  });
}

export async function deleteDocument(docId: string): Promise<ApiMessageResponse> {
  return request<ApiMessageResponse>(`${API_JSON_BASE}/documents/${docId}/delete`, {
    method: "POST",
  });
}
