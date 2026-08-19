"use client";

import Link from "next/link";

import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  RefreshIcon,
  TimerIcon,
} from "@/components/icons";
import { SandboxTopBar } from "@/components/sandbox-topbar";
import {
  getSandboxErrorDetails,
  getSandboxStateLabel,
  type SandboxLifecycleState,
} from "@/lib/sandbox-lifecycle";

interface SandboxLifecycleScreenProps {
  sandboxId: string;
  state: Extract<SandboxLifecycleState, "error" | "expired">;
  errorMessage?: string | null;
  timeLeftLabel?: string | null;
  onRetry?: () => void;
  onCreateNew?: () => void;
  onBackHome?: () => void;
}

export function SandboxLifecycleScreen({
  sandboxId,
  state,
  errorMessage,
  timeLeftLabel,
  onRetry,
  onCreateNew,
  onBackHome,
}: SandboxLifecycleScreenProps) {
  const errorDetails = getSandboxErrorDetails(errorMessage);

  return (
    <main className="sandbox-screen">
      <div className="sandbox-frame">
        <SandboxTopBar
          sandboxId={sandboxId}
          lifecycleState={state}
          demoLabel={getSandboxStateLabel(state)}
          timeLeftLabel={timeLeftLabel}
          showTimeLeft={state === "expired"}
        />

        <section className="sandbox-status-screen">
          <div className="sandbox-status-screen__card">
            <div
              className={`sandbox-status-screen__icon-wrap sandbox-status-screen__icon-wrap--${state}`}
            >
              {state === "error" ? (
                <AlertTriangleIcon className="sandbox-status-screen__icon" />
              ) : (
                <TimerIcon className="sandbox-status-screen__icon" />
              )}
            </div>

            {state === "error" ? (
              <>
                <div className="sandbox-status-screen__copy">
                  <h1>Something went wrong</h1>
                  <p>Failed to start sandbox environment</p>
                </div>

                <div className="sandbox-status-screen__error-panel">
                  <div className="sandbox-status-screen__error-code">
                    <span className="sandbox-status-screen__error-dot" />
                    <span>{errorDetails.code}</span>
                  </div>
                  <div className="sandbox-status-screen__error-body">
                    {errorDetails.details.map((line) => (
                      <span key={line}>{line}</span>
                    ))}
                  </div>
                </div>

                <button
                  className="button button--primary button--full sandbox-status-screen__primary-action"
                  type="button"
                  onClick={onRetry}
                >
                  <RefreshIcon className="button__icon" />
                  Retry
                </button>
              </>
            ) : (
              <>
                <div className="sandbox-status-screen__copy">
                  <h1>Sandbox expired</h1>
                  <p>
                    Your sandbox <code>{sandboxId}</code> has expired after 60 minutes.
                  </p>
                  <p>
                    Spinbox sandboxes automatically expire to keep things clean.
                    <br />
                    Create a new one to continue working.
                  </p>
                </div>

                <button
                  className="button button--primary button--full sandbox-status-screen__primary-action"
                  type="button"
                  onClick={onCreateNew}
                >
                  <RefreshIcon className="button__icon" />
                  Create new sandbox
                </button>
              </>
            )}

            <Link
              className="button button--secondary button--full sandbox-status-screen__secondary-action"
              href="/"
              onClick={onBackHome}
            >
              <ArrowLeftIcon className="button__icon" />
              Back to home
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
