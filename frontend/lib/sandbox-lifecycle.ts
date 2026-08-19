export type SandboxLifecycleState = "loading" | "active" | "error" | "expired";

export const SANDBOX_STATE_LABELS: Record<SandboxLifecycleState, string> = {
  loading: "Loading",
  active: "Active",
  error: "Error",
  expired: "Expired",
};

export const PREVIEW_ERROR_MESSAGE = [
  "CONTAINER_START_FAILED",
  "Error: failed to allocate port 8000.",
  "Exit code: 1 - uvicorn process exited",
].join("\n");

export function getSandboxStateLabel(state: SandboxLifecycleState): string {
  return SANDBOX_STATE_LABELS[state];
}

export function getSandboxErrorDetails(message?: string | null): {
  code: string;
  details: string[];
} {
  const normalized = (message ?? PREVIEW_ERROR_MESSAGE).trim();
  const [firstLine, ...remainingLines] = normalized.split(/\r?\n/).filter(Boolean);

  return {
    code: firstLine || "SANDBOX_START_FAILED",
    details: remainingLines.length ? remainingLines : ["The sandbox could not be started."],
  };
}
