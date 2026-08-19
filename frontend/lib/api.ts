import type {
  ProxyExecutionResult,
  ResetSandboxResult,
  SandboxFile,
  SandboxRoute,
  SandboxSummary,
  ValidationErrorDetail,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail?: ValidationErrorDetail;

  constructor(message: string, status: number, detail?: ValidationErrorDetail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function buildUrl(path: string): string {
  const normalizedBase = API_BASE.endsWith("/") ? API_BASE : `${API_BASE}/`;
  return new URL(path.replace(/^\//, ""), normalizedBase).toString();
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  // Centralize JSON defaults and error handling so components stay focused on
  // product behavior rather than repetitive fetch ceremony.
  const defaultHeaders: Record<string, string> = {};
  if (init?.body !== undefined && init?.body !== null) {
    defaultHeaders["Content-Type"] = "application/json";
  }

  const response = await fetch(buildUrl(path), {
    ...init,
    headers: {
      ...defaultHeaders,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw await readError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function readError(response: Response): Promise<ApiError> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const payload = (await response.json()) as {
      detail?: string | ValidationErrorDetail;
      error?: string;
      kind?: string;
      line?: number | null;
      column?: number | null;
    };
    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail;
      return new ApiError(detail.detail ?? `Request failed with ${response.status}`, response.status, detail);
    }

    const detail =
      typeof payload.detail === "string"
        ? {
            detail: payload.detail,
            error: payload.error,
            kind: payload.kind,
            line: payload.line,
            column: payload.column,
          }
        : undefined;
    return new ApiError(
      detail?.detail ?? payload.error ?? `Request failed with ${response.status}`,
      response.status,
      detail,
    );
  }
  const text = await response.text();
  return new ApiError(text || `Request failed with ${response.status}`, response.status);
}

function normalizeProxyPath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed || trimmed === "/") {
    return "/";
  }
  // The tester accepts relaxed input like `users` and normalizes it to the
  // backend's `/sandbox/{id}/{path}` contract.
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function prepareBody(body: string): { body?: string; contentType?: string } {
  if (!body.trim()) {
    return {};
  }

  try {
    // Preserve pretty-printed JSON in the UI while sending a normalized payload
    // to the backend when the input is valid JSON.
    return {
      body: JSON.stringify(JSON.parse(body)),
      contentType: "application/json",
    };
  } catch {
    return {
      body,
      contentType: "text/plain",
    };
  }
}

export async function createSandbox(): Promise<SandboxSummary> {
  return requestJson<SandboxSummary>("/sandboxes", {
    method: "POST",
  });
}

export async function getSandbox(sandboxId: string): Promise<SandboxSummary> {
  return requestJson<SandboxSummary>(`/sandboxes/${sandboxId}`);
}

export async function deleteSandbox(sandboxId: string): Promise<void> {
  await requestJson<void>(`/sandboxes/${sandboxId}`, {
    method: "DELETE",
  });
}

export async function resetSandbox(sandboxId: string): Promise<ResetSandboxResult> {
  return requestJson<ResetSandboxResult>(`/sandboxes/${sandboxId}/reset`, {
    method: "POST",
  });
}

export async function getSandboxFile(sandboxId: string): Promise<SandboxFile> {
  return requestJson<SandboxFile>(`/sandbox/${sandboxId}/file`);
}

export async function getSandboxRoutes(sandboxId: string): Promise<SandboxRoute[]> {
  return requestJson<SandboxRoute[]>(`/sandbox/${sandboxId}/routes`);
}

export async function updateSandboxFile(sandboxId: string, content: string): Promise<SandboxFile> {
  return requestJson<SandboxFile>(`/sandbox/${sandboxId}/file`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function validateSandboxFile(sandboxId: string, content: string): Promise<ValidationErrorDetail | null> {
  try {
    await requestJson<void>(`/sandbox/${sandboxId}/validate`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    return null;
  } catch (error) {
    if (error instanceof ApiError && error.status === 400 && error.detail) {
      return error.detail;
    }
    throw error;
  }
}

export async function proxySandboxRequest(
  sandboxId: string,
  method: string,
  path: string,
  body: string,
): Promise<ProxyExecutionResult> {
  const normalizedPath = normalizeProxyPath(path);
  const endpoint = normalizedPath === "/" ? `/sandbox/${sandboxId}` : `/sandbox/${sandboxId}${normalizedPath}`;
  const prepared = prepareBody(body);
  // Measure on the client so the response viewer reflects the full round trip
  // the user experiences in the browser.
  const startedAt = performance.now();

  const response = await fetch(buildUrl(endpoint), {
    method,
    headers: prepared.contentType ? { "Content-Type": prepared.contentType } : undefined,
    body: ["GET", "DELETE"].includes(method.toUpperCase()) ? undefined : prepared.body,
    cache: "no-store",
  });

  const durationMs = Math.max(Math.round(performance.now() - startedAt), 1);
  const contentType = response.headers.get("content-type") ?? "application/json";
  const rawText = await response.text();

  let data: unknown = null;
  if (rawText) {
    if (contentType.includes("application/json")) {
      try {
        data = JSON.parse(rawText);
      } catch {
        data = rawText;
      }
    } else {
      data = rawText;
    }
  }

  return {
    status: response.status,
    durationMs,
    data,
    contentType,
  };
}
