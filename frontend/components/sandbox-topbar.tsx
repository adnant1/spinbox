"use client";

import { useState } from "react";

import { ResetIcon, TimerIcon, TrashIcon } from "@/components/icons";
import { Logo } from "@/components/logo";
import { type SandboxLifecycleState } from "@/lib/sandbox-lifecycle";

type PendingAction = "reset" | "delete" | null;

interface SandboxTopBarProps {
  sandboxId: string;
  timeLeftLabel?: string | null;
  resetting?: boolean;
  deleting?: boolean;
  demoLabel?: string;
  lifecycleState?: SandboxLifecycleState;
  showTimeLeft?: boolean;
  onReset?: () => void;
  onDelete?: () => void;
}

export function SandboxTopBar({
  sandboxId,
  timeLeftLabel,
  resetting = false,
  deleting = false,
  demoLabel = "Active",
  lifecycleState = "active",
  showTimeLeft = true,
  onReset,
  onDelete,
}: SandboxTopBarProps) {
  const stateClassName = `sandbox-topbar--${lifecycleState}`;
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);

  const actionsDisabled = resetting || deleting;

  return (
    <header className={`sandbox-topbar ${stateClassName}`}>
      <div className="sandbox-topbar__brand">
        <Logo />
        <span className="sandbox-topbar__divider" />
        <span className="sandbox-topbar__section-label">sandbox</span>
        <div className="sandbox-topbar__id-pill">
          <span className="sandbox-topbar__id-dot" />
          <span className="sandbox-topbar__id-text">{sandboxId}</span>
          <button className="sandbox-topbar__id-copy" type="button" aria-label="Copy sandbox id">
            <span className="sandbox-topbar__id-copy-box" />
          </button>
        </div>
      </div>

      <div className="sandbox-topbar__actions">
        {showTimeLeft && timeLeftLabel ? (
          <div className="sandbox-topbar__timer">
            <TimerIcon className="sandbox-topbar__timer-icon" />
            <span>
              {lifecycleState === "expired" ? timeLeftLabel : `Expires in ${timeLeftLabel}`}
            </span>
          </div>
        ) : null}

        <div className="sandbox-topbar__button sandbox-topbar__button--state" aria-live="polite">
          <span className="sandbox-topbar__menu-dot" />
          <span>{demoLabel}</span>
        </div>

        {pendingAction === "reset" ? (
          <div className="sandbox-topbar__confirm">
            <span className="sandbox-topbar__confirm-label">Reset?</span>
            <button
              className="sandbox-topbar__confirm-action sandbox-topbar__confirm-action--danger"
              type="button"
              onClick={() => {
                setPendingAction(null);
                onReset?.();
              }}
              disabled={actionsDisabled || !onReset}
            >
              Yes
            </button>
            <button
              className="sandbox-topbar__confirm-action"
              type="button"
              onClick={() => setPendingAction(null)}
              disabled={actionsDisabled}
            >
              No
            </button>
          </div>
        ) : (
          <button
            className="sandbox-topbar__button"
            type="button"
            onClick={() => setPendingAction("reset")}
            disabled={actionsDisabled || !onReset}
          >
            <ResetIcon className="sandbox-topbar__button-icon" />
            <span>{resetting ? "Resetting" : "Reset"}</span>
          </button>
        )}

        {pendingAction === "delete" ? (
          <div className="sandbox-topbar__confirm sandbox-topbar__confirm--compact">
            <span className="sandbox-topbar__confirm-label">Delete?</span>
            <button
              className="sandbox-topbar__confirm-action sandbox-topbar__confirm-action--danger"
              type="button"
              onClick={() => {
                setPendingAction(null);
                onDelete?.();
              }}
              disabled={actionsDisabled || !onDelete}
            >
              Yes
            </button>
            <button
              className="sandbox-topbar__confirm-action"
              type="button"
              onClick={() => setPendingAction(null)}
              disabled={actionsDisabled}
            >
              No
            </button>
          </div>
        ) : (
          <button
            className="sandbox-topbar__icon-button"
            type="button"
            onClick={() => setPendingAction("delete")}
            disabled={actionsDisabled || !onDelete}
            aria-label="Delete sandbox"
          >
            <TrashIcon className="sandbox-topbar__button-icon" />
          </button>
        )}
      </div>
    </header>
  );
}
