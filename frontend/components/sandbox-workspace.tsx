"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiTesterPanel } from "@/components/api-tester-panel";
import { EditorPanel } from "@/components/editor-panel";
import { SandboxLifecycleScreen } from "@/components/sandbox-lifecycle-screen";
import { Logo } from "@/components/logo";
import {
  SandboxCreationOverlay,
  type SandboxCreationPhase,
} from "@/components/sandbox-creation-overlay";
import { SandboxTopBar } from "@/components/sandbox-topbar";
import {
  createSandbox,
  deleteSandbox,
  getSandbox,
  getSandboxFile,
  getSandboxRoutes,
  proxySandboxRequest,
  resetSandbox,
  updateSandboxFile,
  validateSandboxFile,
} from "@/lib/api";
import { formatCountdown, formatError, getValidationErrorDetail } from "@/lib/format";
import {
  getSandboxStateLabel,
  type SandboxLifecycleState,
} from "@/lib/sandbox-lifecycle";
import type {
  ProxyExecutionResult,
  SandboxFile,
  SandboxRoute,
  SandboxSummary,
  ValidationErrorDetail,
} from "@/lib/types";

const READY_POLL_INTERVAL_MS = 1000;
const defaultBody = "{}";

interface SandboxWorkspaceProps {
  sandboxId: string;
}

export function SandboxWorkspace({ sandboxId }: SandboxWorkspaceProps) {
  const router = useRouter();
  const [metadata, setMetadata] = useState<SandboxSummary | null>(null);
  const [endpoints, setEndpoints] = useState<SandboxRoute[]>([]);
  const [filePath, setFilePath] = useState("/app/routes.py");
  const [code, setCode] = useState("");
  const [savedCode, setSavedCode] = useState("");
  const [loading, setLoading] = useState(true);
  const [showBootScreen, setShowBootScreen] = useState(true);
  const [bootPhase, setBootPhase] = useState<SandboxCreationPhase>("provisioning");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<ValidationErrorDetail | null>(null);
  const [validationError, setValidationError] = useState<ValidationErrorDetail | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [response, setResponse] = useState<ProxyExecutionResult | null>(null);
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState("/users");
  const [body, setBody] = useState(defaultBody);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [sending, setSending] = useState(false);
  const [now, setNow] = useState(Date.now());
  const dirty = code !== savedCode;

  function syncRequestSelection(nextEndpoints: SandboxRoute[]) {
    const matchingEndpoint = nextEndpoints.find((endpoint) => endpoint.method === method && endpoint.path === path);
    if (matchingEndpoint) {
      return;
    }

    const nextEndpoint = nextEndpoints[0];
    if (nextEndpoint) {
      setMethod(nextEndpoint.method);
      setPath(nextEndpoint.path);
      return;
    }

    setMethod("GET");
  }

  function applySelectedMethod(nextMethod: string) {
    setMethod(nextMethod);
    setResponse(null);
    setRequestError(null);
    if ((nextMethod === "POST" || nextMethod === "PUT" || nextMethod === "PATCH") && !body.trim()) {
      setBody(defaultBody);
    }
  }

  async function waitForNextPoll() {
    await new Promise((resolve) => {
      window.setTimeout(resolve, READY_POLL_INTERVAL_MS);
    });
  }

  function applyWorkspaceState(
    nextMetadata: SandboxSummary,
    nextFile: SandboxFile,
    nextEndpoints: SandboxRoute[],
  ) {
    setMetadata(nextMetadata);
    setFilePath(nextFile.path);
    setCode(nextFile.content);
    setSavedCode(nextFile.content);
    setEndpoints(nextEndpoints);
    syncRequestSelection(nextEndpoints);
  }

  async function waitForSandboxReady(targetSandboxId: string): Promise<SandboxSummary> {
    for (;;) {
      const nextMetadata = await getSandbox(targetSandboxId);

      if (nextMetadata.status === "error") {
        throw new Error(nextMetadata.error_detail ?? "Sandbox failed to start.");
      }

      if (nextMetadata.status === "active") {
        return nextMetadata;
      }

      await waitForNextPoll();
    }
  }

  useEffect(() => {
    let active = true;
    async function loadSandboxWorkspace() {
      setShowBootScreen(true);
      setBootPhase("provisioning");
      setLoading(true);
      setLoadError(null);

      try {
        const nextMetadata = await waitForSandboxReady(sandboxId);

        if (!active) {
          return;
        }

        const [nextFile, nextEndpoints] = await Promise.all([
          getSandboxFile(sandboxId),
          getSandboxRoutes(sandboxId),
        ]);

        if (!active) {
          return;
        }

        applyWorkspaceState(nextMetadata, nextFile, nextEndpoints);
        setBootPhase("finalizing");
      } catch (caughtError) {
        if (active) {
          setLoadError(formatError(caughtError));
          setShowBootScreen(false);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadSandboxWorkspace();

    return () => {
      active = false;
    };
  }, [sandboxId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!metadata || !dirty) {
      setValidationError(null);
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void (async () => {
        try {
          const detail = await validateSandboxFile(sandboxId, code);
          if (!controller.signal.aborted) {
            setValidationError(detail);
          }
        } catch {
          if (!controller.signal.aborted) {
            setValidationError(null);
          }
        }
      })();
    }, 450);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [code, dirty, metadata, sandboxId]);

  useEffect(() => {
    if (!dirty) {
      setSaveError(null);
    }
  }, [dirty]);

  const timeLeftSeconds = metadata
    ? Math.max(Math.floor((new Date(metadata.expires_at).getTime() - now) / 1000), 0)
    : 0;
  const derivedState = useMemo<SandboxLifecycleState>(() => {
    if (showBootScreen || loading || metadata?.status === "loading") {
      return "loading";
    }
    if (loadError || metadata?.status === "error") {
      return "error";
    }
    if (metadata && timeLeftSeconds <= 0) {
      return "expired";
    }
    return "active";
  }, [loadError, loading, metadata, showBootScreen, timeLeftSeconds]);
  const currentState = derivedState;
  const currentStateLabel = getSandboxStateLabel(currentState);

  async function refreshMetadata() {
    try {
      const nextMetadata = await getSandbox(sandboxId);
      if (nextMetadata.status === "active") {
        setMetadata(nextMetadata);
      }
    } catch {
      // Best-effort refresh so the visible timer stays reasonably current.
    }
  }

  async function reloadSandboxEnvironment() {
    setShowBootScreen(true);
    setBootPhase("provisioning");
    setLoading(true);
    setLoadError(null);

    try {
      await resetSandbox(sandboxId);
      const nextMetadata = await waitForSandboxReady(sandboxId);
      const [nextFile, nextEndpoints] = await Promise.all([
        getSandboxFile(sandboxId),
        getSandboxRoutes(sandboxId),
      ]);

      applyWorkspaceState(nextMetadata, nextFile, nextEndpoints);
      setBody(defaultBody);
      setResponse(null);
      setBootPhase("finalizing");
    } catch (caughtError) {
      setLoadError(formatError(caughtError));
      setShowBootScreen(false);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateReplacementSandbox() {
    try {
      const sandbox = await createSandbox();
      router.push(sandbox.url);
    } catch (caughtError) {
      setLoadError(formatError(caughtError));
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);

    try {
      const updated = await updateSandboxFile(sandboxId, code);
      const nextEndpoints = await getSandboxRoutes(sandboxId);
      setFilePath(updated.path);
      setCode(updated.content);
      setSavedCode(updated.content);
      setValidationError(null);
      setEndpoints(nextEndpoints);
      syncRequestSelection(nextEndpoints);
      await refreshMetadata();
    } catch (caughtError) {
      setSaveError(
        getValidationErrorDetail(caughtError) ?? {
          detail: formatError(caughtError),
          kind: "save_error",
        },
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setResetting(true);
    setSaveError(null);
    setRequestError(null);

    try {
      await reloadSandboxEnvironment();
    } catch (caughtError) {
      setSaveError(
        getValidationErrorDetail(caughtError) ?? {
          detail: formatError(caughtError),
          kind: "save_error",
        },
      );
    } finally {
      setResetting(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);

    try {
      await deleteSandbox(sandboxId);
      router.push("/");
    } catch (caughtError) {
      setLoadError(formatError(caughtError));
    } finally {
      setDeleting(false);
    }
  }

  async function handleSend() {
    setSending(true);
    setRequestError(null);

    try {
      const result = await proxySandboxRequest(sandboxId, method, path, body);
      setResponse(result);
      await refreshMetadata();
    } catch (caughtError) {
      setRequestError(formatError(caughtError));
    } finally {
      setSending(false);
    }
  }

  if (currentState === "loading") {
    return (
      <main className="sandbox-screen">
        <SandboxCreationOverlay
          inline
          sandboxId={sandboxId}
          lifecycleState={currentState}
          phase={bootPhase}
          onSequenceComplete={() => {
            setShowBootScreen(false);
          }}
        />
      </main>
    );
  }

  if (currentState === "error") {
    return (
      <SandboxLifecycleScreen
        sandboxId={metadata?.id ?? sandboxId}
        state="error"
        errorMessage={loadError}
        onRetry={() => void reloadSandboxEnvironment()}
      />
    );
  }

  if (!metadata) {
    return (
      <main className="sandbox-screen sandbox-screen--centered">
        <div className="empty-state">
          <Logo />
          <h1>Sandbox unavailable</h1>
          <p>This sandbox could not be loaded.</p>
          <Link className="button button--primary" href="/">
            Return home
          </Link>
        </div>
      </main>
    );
  }

  if (currentState === "expired") {
    return (
      <SandboxLifecycleScreen
        sandboxId={metadata.id}
        state="expired"
        timeLeftLabel="00:00"
        onCreateNew={handleCreateReplacementSandbox}
      />
    );
  }

  return (
    <main className="sandbox-screen">
      <div className="sandbox-frame">
        <SandboxTopBar
          sandboxId={metadata.id}
          lifecycleState={currentState}
          timeLeftLabel={formatCountdown(timeLeftSeconds)}
          resetting={resetting}
          deleting={deleting}
          demoLabel={currentStateLabel}
          onReset={handleReset}
          onDelete={handleDelete}
        />

        <div className="sandbox-workspace">
          <div className="sandbox-workspace__tester">
            <ApiTesterPanel
              endpoints={endpoints}
              method={method}
              path={path}
              body={body}
              sending={sending}
              error={requestError}
              response={response}
              onEndpointSelect={(endpoint) => {
                applySelectedMethod(endpoint.method);
                setPath(endpoint.path);
              }}
              onPathChange={(nextPath) => {
                setPath(nextPath);
                setResponse(null);
                setRequestError(null);
              }}
              onBodyChange={(nextBody) => {
                setBody(nextBody);
                setResponse(null);
                setRequestError(null);
              }}
              onSend={handleSend}
            />
          </div>

          <div className="sandbox-workspace__divider">
            <span className="sandbox-workspace__divider-line" />
          </div>

          <div className="sandbox-workspace__editor">
            <EditorPanel
              path={filePath}
              value={code}
              dirty={dirty}
              saving={saving}
              error={saveError}
              validationError={validationError}
              onChange={setCode}
              onSave={handleSave}
            />
          </div>
        </div>
      </div>
    </main>
  );
}
