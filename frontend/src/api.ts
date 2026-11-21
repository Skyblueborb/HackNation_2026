/**
 * Minimalny klient API. Jeśli backend nie działa, wywołania rzucają błąd,
 * a App.tsx łapie go i pokazuje komunikat — demo bez backendu dalej działa.
 */

const BASE = '/api';
const TOKEN = (import.meta.env as Record<string, string>)?.VITE_API_TOKEN || '';

export interface StoredDocument {
  document_id: string;
  client_doc_id: string | null;
  doc_class: 'odwolanie' | 'pelnomocnictwo' | 'przelew';
  source_name: string | null;
  canonical_json: any;
  predicted_json: any;
  provenance_json: any;
  correction_count: number;
  latest_correction_session_id: string | null;
  created_at: string | null;
}

export interface IngestResult {
  document_id: string;
  doc_class: string;
  created: boolean;
  correction_session_id: string | null;
  validation_errors?: string[];
}

/** Stabilny identyfikator karty — jedna karta = jeden zestaw dokumentów. */
export function getClientToken(): string {
  const KEY = 'o2j-client-token';
  let token = sessionStorage.getItem(KEY);
  if (!token) {
    token = typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random()}`;
    sessionStorage.setItem(KEY, token);
  }
  return token;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(TOKEN ? { 'X-API-Token': TOKEN } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

/** Zapisz wynik (pierwszy raz) albo poprawkę (gdy JSON się zmienił). */
export function ingestDocument(payload: {
  client_token: string;
  client_doc_id: string;   // jeden plik z ZIP-a = jeden dokument
  doc_class: 'odwolanie' | 'pelnomocnictwo' | 'przelew';
  canonical_json: unknown;
  source_name?: string;
  provenance_json?: unknown;
}): Promise<IngestResult> {
  return request<IngestResult>('/documents/ingest', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** Pobierz wszystkie wyniki zapisane dla tej karty. */
export function listDocuments(): Promise<StoredDocument[]> {
  return request<StoredDocument[]>(
    `/documents?client_token=${encodeURIComponent(getClientToken())}`,
  );
}
