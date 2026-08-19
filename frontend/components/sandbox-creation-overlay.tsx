"use client";

import { useEffect, useState } from "react";
import { Boxes } from "lucide-react";

import { CheckCircleIcon } from "@/components/icons";
import { SandboxTopBar } from "@/components/sandbox-topbar";
import {
  getSandboxStateLabel,
  type SandboxLifecycleState,
} from "@/lib/sandbox-lifecycle";

const STEP_REVEAL_PAUSE_MS = 320;
const FINALIZING_STEP_DELAY_MS = 240;

export const SANDBOX_CREATION_STEPS = [
  { id: 1, label: "Starting container", delay: 0 },
  { id: 2, label: "Installing dependencies", delay: 700 },
  { id: 3, label: "Starting FastAPI server", delay: 1500 },
  { id: 4, label: "Mounting SQLite database", delay: 2000 },
] as const;

export const SANDBOX_CREATION_DURATION_MS =
  (SANDBOX_CREATION_STEPS.length - 1) * FINALIZING_STEP_DELAY_MS + STEP_REVEAL_PAUSE_MS;

export type SandboxCreationPhase = "provisioning" | "finalizing";

interface SandboxCreationOverlayProps {
  title?: string;
  subtitle?: string;
  inline?: boolean;
  sandboxId?: string;
  lifecycleState?: SandboxLifecycleState;
  phase?: SandboxCreationPhase;
  onSequenceComplete?: () => void;
}

export function SandboxCreationOverlay({
  title = "Preparing your environment",
  subtitle = "This takes about 5 seconds",
  inline = false,
  sandboxId = "sb-7wsjkono",
  lifecycleState = "loading",
  phase = "provisioning",
  onSequenceComplete,
}: SandboxCreationOverlayProps) {
  const [visibleStepCount, setVisibleStepCount] = useState(1);

  useEffect(() => {
    if (phase === "provisioning") {
      setVisibleStepCount(1);
      return;
    }

    setVisibleStepCount(1);
    const timers = SANDBOX_CREATION_STEPS.slice(1).map((_, index) =>
      window.setTimeout(() => {
        setVisibleStepCount(index + 2);
      }, (index + 1) * FINALIZING_STEP_DELAY_MS),
    );

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [phase]);

  useEffect(() => {
    if (phase !== "finalizing" || visibleStepCount !== SANDBOX_CREATION_STEPS.length) {
      return;
    }

    const completionTimer = window.setTimeout(() => {
      onSequenceComplete?.();
    }, STEP_REVEAL_PAUSE_MS);

    return () => {
      window.clearTimeout(completionTimer);
    };
  }, [onSequenceComplete, phase, visibleStepCount]);

  return (
    <div className={inline ? "transition-screen transition-screen--inline" : "transition-screen"}>
      <div className="transition-screen__surface">
        <SandboxTopBar
          sandboxId={sandboxId}
          lifecycleState={lifecycleState}
          demoLabel={getSandboxStateLabel(lifecycleState)}
          showTimeLeft={false}
        />
        <div className="transition-screen__body">
          <div className="transition-screen__center">
            <div className="transition-screen__icon-wrap">
              <div className="transition-screen__icon-ring" />
              <div className="transition-screen__icon">
                <Boxes className="transition-screen__icon-glyph" aria-hidden="true" />
              </div>
            </div>
            <div className="transition-screen__copy">
              <h1>{title}</h1>
              <p>{subtitle}</p>
            </div>
            <div className="transition-screen__steps">
              {SANDBOX_CREATION_STEPS.slice(0, visibleStepCount).map((step, index) => {
                const isActive = index === visibleStepCount - 1;
                const isComplete = index < visibleStepCount - 1;

                return (
                  <div
                    key={step.id}
                    className={`transition-step${isActive ? " transition-step--active" : ""}`}
                  >
                    {isComplete ? (
                      <CheckCircleIcon className="transition-step__icon transition-step__icon--complete" />
                    ) : (
                      <span className="transition-step__spinner" aria-hidden="true" />
                    )}
                    <span>{step.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
