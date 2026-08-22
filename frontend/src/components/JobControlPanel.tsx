import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  cancelJob,
  getJobControl,
  resumeJob,
  retryJob,
} from "../api/client";
import type { JobControlView, StageRunView } from "../api/types";
import { Diagnostics } from "./Feedback";
import { StatusBadge } from "./StatusBadge";

type JobAction = "RETRY" | "CANCEL" | "RESUME";

interface JobControlPanelProps {
  jobId: string;
  onChange?: (view: JobControlView) => void;
}

interface FeedbackState {
  kind: "success" | "error";
  message: string;
  moveFocus: boolean;
}

type CopyState = "idle" | "copied" | "failed";

const ACTION_COPY: Record<
  JobAction,
  { button: string; pending: string; success: string }
> = {
  RETRY: {
    button: "Reintentar job",
    pending: "Solicitando reintento…",
    success: "El reintento quedó solicitado y persistido.",
  },
  CANCEL: {
    button: "Cancelar job",
    pending: "Solicitando cancelación…",
    success: "La cancelación quedó solicitada y persistida.",
  },
  RESUME: {
    button: "Reanudar job",
    pending: "Solicitando reanudación…",
    success: "La reanudación quedó solicitada y persistida.",
  },
};

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "No se pudo aplicar el control solicitado.";
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "Pendiente";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("es-CL");
}

function StageRunItem({ run }: { run: StageRunView }) {
  return (
    <li>
      <div className="chip-row">
        <strong>{run.stage.replaceAll("_", " ")}</strong>
        <StatusBadge status={run.status} />
        <span className="meta-chip">Intento {run.attempt ?? 1}</span>
      </div>
      <dl className="activity-summary">
        <div>
          <dt>Inicio</dt>
          <dd>{formatTimestamp(run.started_at)}</dd>
        </div>
        <div>
          <dt>Término</dt>
          <dd>{formatTimestamp(run.finished_at)}</dd>
        </div>
        <div>
          <dt>Clase / retry</dt>
          <dd>{run.failure_class ?? "Sin fallo"} · {run.retryable ? "reintentable" : "no reintentable"}</dd>
        </div>
      </dl>
      <Diagnostics items={run.diagnostics} />
    </li>
  );
}

export function JobControlPanel({ jobId, onChange }: JobControlPanelProps) {
  const headingId = useId();
  const helpId = useId();
  const [view, setView] = useState<JobControlView | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<JobAction | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [reload, setReload] = useState(0);
  const feedbackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFeedback(null);
    setCopyState("idle");
    getJobControl(jobId)
      .then((next) => {
        if (cancelled) return;
        setView(next);
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoading(false);
        setFeedback({ kind: "error", message: errorMessage(error), moveFocus: false });
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, reload]);

  useEffect(() => {
    if (feedback?.moveFocus) feedbackRef.current?.focus();
  }, [feedback]);

  const actions = useMemo(
    () =>
      view ? (view.allowed_actions ?? []) : [],
    [view],
  );

  const runAction = async (action: JobAction) => {
    setPending(action);
    setFeedback(null);
    try {
      const next = await {
        RETRY: retryJob,
        CANCEL: cancelJob,
        RESUME: resumeJob,
      }[action](jobId);
      setView(next);
      onChange?.(next);
      setFeedback({
        kind: "success",
        message: ACTION_COPY[action].success,
        moveFocus: true,
      });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: errorMessage(error),
        moveFocus: true,
      });
    } finally {
      setPending(null);
    }
  };

  const copyJobId = async () => {
    try {
      await navigator.clipboard.writeText(jobId);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  return (
    <section
      aria-busy={loading || pending !== null}
      aria-labelledby={headingId}
      className="form-card job-control-panel"
    >
      <div className="section-heading compact-heading">
        <span className="section-number" aria-hidden="true">↻</span>
        <div>
          <h2 id={headingId}>Control durable del job</h2>
          <p id={helpId}>
            Retry, cancel y resume pertenecen a la aplicación; cada etapa conserva su historial.
          </p>
        </div>
      </div>

      {loading && !view && (
        <p aria-live="polite">Cargando controles y ejecuciones por etapa…</p>
      )}

      {view && (
        <>
          <div className="job-reference">
            <div>
              <span className="mini-label">Identificador durable</span>
              <code>{jobId}</code>
            </div>
            <button
              className="button button-secondary"
              onClick={() => void copyJobId()}
              type="button"
            >
              {copyState === "copied" ? "Job ID copiado" : "Copiar job ID"}
            </button>
          </div>
          {copyState !== "idle" && (
            <p
              aria-live={copyState === "failed" ? "assertive" : "polite"}
              className={`job-copy-status ${copyState === "failed" ? "error-text" : ""}`}
              role={copyState === "failed" ? "alert" : undefined}
            >
              {copyState === "copied"
                ? "Identificador copiado al portapapeles."
                : "No se pudo copiar automáticamente; selecciona el identificador visible."}
            </p>
          )}
          <div className="dual-status-grid">
            <article className="status-panel">
              <span className="mini-label">Job actual</span>
              <div className="status-panel-title">
                <StatusBadge status={view.job.status} />
                <strong>{Math.round(view.job.progress * 100)}%</strong>
              </div>
              <dl>
                <div><dt>Etapa</dt><dd>{view.job.stage.replaceAll("_", " ")}</dd></div>
                <div><dt>Intento</dt><dd>{view.job.attempt}</dd></div>
                {view.resumable_stage && (
                  <div>
                    <dt>Reanudable desde</dt>
                    <dd>{view.resumable_stage.replaceAll("_", " ")}</dd>
                  </div>
                )}
              </dl>
            </article>
          </div>

          <div className="reference-list">
            <span className="mini-label">Ejecuciones por etapa</span>
            {(view.stage_runs ?? []).length > 0 ? (
              <ol aria-label="Ejecuciones por etapa">
                {(view.stage_runs ?? []).map((run, index) => (
                  <StageRunItem
                    key={run.stage_run_id ?? `${run.stage}:${run.attempt ?? index}`}
                    run={run}
                  />
                ))}
              </ol>
            ) : (
              <p className="muted">Todavía no hay ejecuciones de etapa registradas.</p>
            )}
          </div>

          {(view.control_records ?? []).length > 0 && (
            <div className="table-scroll" tabIndex={0} aria-label="Historial de controles del job">
              <table className="batch-table">
                <caption>Controles durables aplicados</caption>
                <thead><tr><th scope="col">Acción</th><th scope="col">Estado</th><th scope="col">Intento fuente</th><th scope="col">Etapa destino</th><th scope="col">Motivo</th><th scope="col">Solicitado</th></tr></thead>
                <tbody>{(view.control_records ?? []).map((record) => <tr key={record.control_id}><th scope="row">{record.action}</th><td>{record.status}</td><td>{record.source_attempt}</td><td>{record.target_stage ?? "—"}</td><td>{record.reason_code}</td><td>{formatTimestamp(record.requested_at)}</td></tr>)}</tbody>
              </table>
            </div>
          )}

          <div className="form-actions">
            {actions.length > 0 ? (
              <div className="chip-row">
                {actions.map((action) => (
                  <button
                    aria-describedby={helpId}
                    className={action === "CANCEL" ? "button button-secondary" : "button button-primary"}
                    disabled={pending !== null}
                    key={action}
                    onClick={() => void runAction(action)}
                    type="button"
                  >
                    {pending === action ? ACTION_COPY[action].pending : ACTION_COPY[action].button}
                  </button>
                ))}
              </div>
            ) : (
              <p className="muted">Este estado no admite acciones de control.</p>
            )}
            <button
              className="button button-quiet"
              disabled={loading || pending !== null}
              onClick={() => setReload((current) => current + 1)}
              type="button"
            >
              Actualizar controles
            </button>
          </div>
        </>
      )}

      {feedback && (
        <div
          aria-live={feedback.kind === "error" ? "assertive" : "polite"}
          className={`notice notice-${feedback.kind}`}
          ref={feedbackRef}
          role={feedback.kind === "error" ? "alert" : "status"}
          tabIndex={-1}
        >
          <strong>{feedback.kind === "error" ? "No se aplicó la acción." : "Control actualizado."}</strong>
          <span>{feedback.message}</span>
          {!view && (
            <button
              className="button button-secondary"
              onClick={() => setReload((current) => current + 1)}
              type="button"
            >
              Volver a cargar controles
            </button>
          )}
        </div>
      )}
    </section>
  );
}
