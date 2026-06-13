import type { JobPhase, JobStatus } from "../api/client";

// Steps: Upload(0) → In Queue(1) → Starting(2) → Transcribing(3) → Done(4)
const STAGES = [
  { label: "Upload"          },
  { label: "In Queue"        },
  { label: "Starting"        },
  { label: "Transcribing"    },
  { label: "Done"            },
];

// The pipeline STEP is driven by the backend-reported phase — the data status
// (PENDING/PROCESSING/...) is a separate explanation and does not move the flow.
export function phaseToStep(phase: JobPhase | null): number {
  switch (phase) {
    case "TRANSCRIBING":
    case "STITCHING":   return 3; // Transcribing
    case "STARTING":    return 2; // Starting
    case "QUEUED":
    default:            return 1; // In Queue
  }
}

export function activeStepIndex(
  status: JobStatus | null,
  phase: JobPhase | null,
): number {
  // COMPLETED is the only status that advances the flow (to Done); everything
  // else follows the phase (the furthest step the job reached).
  if (status === "COMPLETED") return 4;
  return phaseToStep(phase);
}

/** Human-readable data state — shown as an explanatory badge, not the flow. */
export function statusLabel(status: JobStatus | null): string {
  switch (status) {
    case "PENDING":    return "Pending";
    case "PROCESSING": return "Processing";
    case "COMPLETED":  return "Completed";
    case "FAILED":     return "Failed";
    default:           return status ?? "";
  }
}

interface Props {
  status: JobStatus | null;
  phase?: JobPhase | null;
}

export function Stepper({ status, phase = null }: Props) {
  const isFailed = status === "FAILED";
  const current = isFailed ? phaseToStep(phase) : activeStepIndex(status, phase);

  return (
    <ol className="stepper">
      {STAGES.map((stage, i) => {
        const dotState =
          i < current                    ? "done"
          : i === current && isFailed    ? "failed"
          : i === current                ? "active"
          : "upcoming";

        const connState =
          i === 0                        ? null
          : i < current                  ? "filled"
          : i === current && isFailed    ? "failed"
          : i === current                ? "flowing"
          : "idle";

        return (
          <li key={i} className={`stepper__step stepper__step--${dotState}`}>
            {connState !== null && (
              <span className="stepper__connector">
                <span className={`stepper__connector-fill stepper__connector-fill--${connState}`} />
              </span>
            )}
            <span className="stepper__dot">
              {i < current ? (
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <polyline points="2,6 5,9 10,3" stroke="currentColor"
                    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : i === current && isFailed ? (
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <line x1="3" y1="3" x2="9" y2="9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  <line x1="9" y1="3" x2="3" y2="9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              ) : (
                <span>{i + 1}</span>
              )}
            </span>
            <span className="stepper__label">{stage.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
