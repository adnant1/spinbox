export interface SandboxSummary {
  id: string;
  url: string;
  placeholder_url: string;
  status: "loading" | "active" | "error" | "expired";
  error_detail: string | null;
  created_at: string;
  expires_at: string;
  ttl_seconds: number;
}

export interface SandboxFile {
  id: string;
  path: string;
  content: string;
}

export interface SandboxRoute {
  method: string;
  path: string;
  param_names: string[];
}

export interface ResetSandboxResult {
  id: string;
  message: string;
}

export interface ProxyExecutionResult {
  status: number;
  durationMs: number;
  data: unknown;
  contentType: string;
}

export interface ValidationErrorDetail {
  error?: string;
  detail: string;
  kind?: string;
  line?: number | null;
  column?: number | null;
}
