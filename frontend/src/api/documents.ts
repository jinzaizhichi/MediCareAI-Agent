/**
 * Document upload and multimodal parsing API client.
 * POST /api/v1/documents/upload  — Upload a file
 * GET  /api/v1/documents/{id}/result — Poll for parse result
 * DEL  /api/v1/documents/{id} — Delete
 */

import { getToken } from './client';
import type { DocumentParseResult, DocumentUploadResponse } from '../types/agent';

const API_BASE = '/api/v1/documents';

function getGuestToken(): string | null {
  return localStorage.getItem('guest_token');
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  const guest = getGuestToken();
  if (token) return { Authorization: `Bearer ${token}` };
  if (guest) return { 'X-Guest-Token': guest };
  return {};
}

export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Upload failed: HTTP ${res.status}`);
  }

  return res.json();
}

export async function getParseResult(fileId: string): Promise<DocumentParseResult> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(fileId)}/result`, {
    headers: authHeaders(),
  });

  if (!res.ok) {
    if (res.status === 404) {
      return { status: 'failed', file_id: fileId, error: 'Document not found' };
    }
    throw new Error(`Failed to get result: HTTP ${res.status}`);
  }

  return res.json();
}

export async function deleteDocument(fileId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(fileId)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });

  if (!res.ok && res.status !== 404) {
    throw new Error(`Failed to delete: HTTP ${res.status}`);
  }
}
