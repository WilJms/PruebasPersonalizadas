import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "wouter";
import {
  createSubmission,
  getJob,
  getSubmission,
  getSubmissionEstimate,
  runSubmission,
  uploadSubmissionArtifact,
} from "../api/client";
import type { CostEstimate, JobStatus, SubmissionDomainState, SubmissionResource } from "../api/types";
import { Diagnostics, ErrorNotice } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { useRouteState } from "../routing";

const SUBMISSION_ACCEPT = ".pdf,.txt,.md,text/plain,text/markdown,application/pdf";

const PIPELINE_STAGES: Array<{ state: SubmissionDomainState; label: string; detail: string }> = [
  { state: "VALIDATING", label: "Validación", detail: "MIME, tamaño y hash" },
  { state: "PARSING", label: "Extracción", detail: "Evidencia con procedencia" },
  { state: "MAPPING_OPPORTUNITIES", label: "Mapeo", detail: "Variantes y oportunidades" },
  { state: "PLANNING", label: "Plan exacto", detail: "N primarias y reserva" },
  { state: "GENERATING", label: "Preguntas", detail: "Una por oportunidad" },
  { state: "VALIDATING_QUESTIONS", label: "Revisión", detail: "Reglas y scores P08" },
  { state: "GUIDE_READY", label: "Guía", detail: "Objeto estructurado" },
  { state: "NEEDS_REVIEW", label: "Revisión humana", detail: "Evidence-first" },
];

const TERMINAL_DOMAIN_STATES: SubmissionDomainState[] = [
  "NEEDS_REVIEW",
  "APPROVED",
  "INSUFFICIENT_RELEVANT_EVIDENCE",
  "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
  "EVIDENCE_MAPPING_UNCERTAIN",
  "ASSESSMENT_PLAN_INFEASIBLE",
  "TECHNICAL_FAILURE",
  "REJECTED_SECURITY",
  "CANCELLED",
];

export function SubmissionStartPage() {
  const { activityId = "" } = useParams();
  const [, navigate] = useLocation();
  const [subjectRef, setSubjectRef] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [phase, setPhase] = useState("Cargar e iniciar pipeline");
  const [error, setError] = useState<unknown>(null);
  const [preparedSubmissionId, setPreparedSubmissionId] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || !subjectRef.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      setPhase("Creando entrega…");
      const submission = await createSubmission(activityId, subjectRef.trim());
      setPhase("Guardando archivo privado…");
      await uploadSubmissionArtifact(submission.submission_id, file);
      setPhase("Calculando estimación…");
      const nextEstimate = await getSubmissionEstimate(submission.submission_id);
      setPreparedSubmissionId(submission.submission_id);
      setEstimate(nextEstimate);
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
      setPhase("Cargar e iniciar pipeline");
    }
  };

  const start = async () => {
    if (!preparedSubmissionId || !estimate?.within_limit) return;
    setSubmitting(true);
    setError(null);
    setPhase("Iniciando job…");
    try {
      const operation = await runSubmission(preparedSubmissionId);
      navigate(`/submissions/${preparedSubmissionId}`, {
        replace: true,
        state: { jobId: operation.job_id },
      });
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="content-stack narrow-content">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Una entrega</span>
          <h1>Carga el trabajo a verificar</h1>
          <p>El archivo se procesa de forma independiente y nunca se mezcla con evidencia de otra persona.</p>
        </div>
        <span className="step-pill">2 de 3 · Entrega</span>
      </header>

      <form className="submission-card" onSubmit={(event) => void submit(event)}>
        <div className="submission-safety-note">
          <span aria-hidden="true">◎</span>
          <div>
            <strong>Contenido no confiable</strong>
            <p>No se ejecutan macros, código, fórmulas, enlaces ni instrucciones dentro del archivo.</p>
          </div>
        </div>

        <label className="field">
          <span>Referencia seudónima</span>
          <input
            maxLength={128}
            name="subject_ref"
            onChange={(event) => setSubjectRef(event.target.value)}
            pattern="[a-z][a-z0-9_-]{2,127}"
            placeholder="estudiante_014"
            required
            value={subjectRef}
          />
          <small>No ingreses nombre, correo ni matrícula.</small>
        </label>

        <label className={`drop-field drop-field-large ${file ? "has-file" : ""}`}>
          <span className="drop-icon" aria-hidden="true">↑</span>
          <strong>{file?.name ?? "Selecciona un único entregable"}</strong>
          <span>{file ? `${Math.max(1, Math.round(file.size / 1024))} KB` : "PDF digital, TXT o Markdown"}</span>
          <input
            accept={SUBMISSION_ACCEPT}
            name="submission_file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
            type="file"
          />
        </label>

        <div className="format-guardrail">
          <span>PDF digital</span>
          <span>TXT</span>
          <span>MD</span>
          <small>Solo formatos seguros habilitados en esta etapa.</small>
        </div>

        <ErrorNotice error={error} />
        {estimate ? (
          <section className="estimate-panel" aria-live="polite">
            <div>
              <span className="eyebrow">Estimación preflight</span>
              <p>{estimate.estimated_model_calls} llamadas · límite superior USD {estimate.upper_bound_cost_usd.toFixed(2)} de USD {estimate.authorized_limit_usd.toFixed(2)}.</p>
              <small>Calculada {new Date(estimate.generated_at).toLocaleString()} · no es una promesa de precio.</small>
            </div>
            <button className="button button-primary" disabled={!estimate.within_limit || submitting} onClick={() => void start()} type="button">
              {submitting ? phase : "Confirmar e iniciar pipeline"}
            </button>
          </section>
        ) : (
          <button
            className="button button-primary button-full"
            disabled={!file || !subjectRef.trim() || submitting}
            type="submit"
          >
            {submitting ? phase : "Cargar y estimar"}
          </button>
        )}
      </form>
    </div>
  );
}

export function SubmissionProgressPage() {
  const { submissionId = "" } = useParams();
  const [, navigate] = useLocation();
  const initialJobId = useRouteState<{ jobId?: string }>()?.jobId;
  const [submission, setSubmission] = useState<SubmissionResource | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [starting, setStarting] = useState(false);

  const refresh = useCallback(async () => {
    const nextSubmission = await getSubmission(submissionId);
    setSubmission(nextSubmission);
    const jobId = nextSubmission.active_job_id ?? initialJobId;
    if (jobId) setJob(await getJob(jobId));
    setError(null);
    return nextSubmission;
  }, [initialJobId, submissionId]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await refresh();
        if (
          cancelled ||
          TERMINAL_DOMAIN_STATES.includes(next.status) ||
          (next.status === "UPLOADED" && !next.active_job_id)
        ) return;
        timer = window.setTimeout(() => void poll(), 1800);
      } catch (caught) {
        if (!cancelled) setError(caught);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [refresh]);

  useEffect(() => {
    if (submission?.status !== "UPLOADED" || submission.active_job_id || estimate) return;
    getSubmissionEstimate(submission.submission_id)
      .then(setEstimate)
      .catch(setError);
  }, [estimate, submission]);

  const startRecovered = async () => {
    if (!submission || !estimate?.within_limit) return;
    setStarting(true);
    setError(null);
    try {
      const operation = await runSubmission(submission.submission_id);
      setJob(operation);
      await refresh();
    } catch (caught) {
      setError(caught);
    } finally {
      setStarting(false);
    }
  };

  if (!submission) {
    return (
      <div className="content-stack">
        <section className="processing-card" aria-live="polite">
          <span className="spinner spinner-large" aria-hidden="true" />
          <h1>Recuperando estado durable</h1>
          <p>El job continúa aunque cierres esta ventana.</p>
        </section>
        <ErrorNotice error={error} />
      </div>
    );
  }

  return (
    <SubmissionProgress
      job={job}
      estimate={estimate}
      onOpenAssessment={() => navigate(`/submissions/${submission.submission_id}/review`)}
      onStart={() => void startRecovered()}
      starting={starting}
      submission={submission}
    />
  );
}

export function SubmissionProgress({
  submission,
  job,
  estimate = null,
  onOpenAssessment,
  onStart = () => undefined,
  starting = false,
}: {
  submission: SubmissionResource;
  job: JobStatus | null;
  estimate?: CostEstimate | null;
  onOpenAssessment: () => void;
  onStart?: () => void;
  starting?: boolean;
}) {
  const currentIndex = useMemo(
    () => PIPELINE_STAGES.findIndex((item) => item.state === submission.status),
    [submission.status],
  );
  const canReview =
    Boolean(submission.assessment_id) &&
    ["GUIDE_READY", "NEEDS_REVIEW", "APPROVED"].includes(submission.status);
  const canStart = submission.status === "UPLOADED" && !submission.active_job_id;

  return (
    <div className="content-stack">
      <header className="page-heading page-heading-actions">
        <div>
          <span className="eyebrow">Entrega · {submission.subject_ref}</span>
          <h1>Pipeline por evidencia</h1>
          <p>El estado técnico y el resultado de dominio se muestran por separado.</p>
        </div>
        <span className="step-pill">2 de 3 · Procesamiento</span>
      </header>

      <section className="dual-status-grid">
        <article className="status-panel">
          <span className="mini-label">Job técnico</span>
          <div className="status-panel-title">
            <StatusBadge status={job?.status ?? "QUEUED"} />
            <strong>{Math.round((job?.progress ?? 0) * 100)}%</strong>
          </div>
          <div className="progress-track"><span style={{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }} /></div>
          <dl>
            <div><dt>Etapa</dt><dd>{job?.stage?.replaceAll("_", " ") ?? "Pendiente"}</dd></div>
            <div><dt>Intento</dt><dd>{job?.attempt ?? 0}</dd></div>
          </dl>
        </article>
        <article className="status-panel">
          <span className="mini-label">Estado de dominio</span>
          <div className="status-panel-title">
            <StatusBadge status={submission.status} />
            <strong>{Math.round(submission.progress * 100)}%</strong>
          </div>
          <div className="progress-track"><span style={{ width: `${Math.round(submission.progress * 100)}%` }} /></div>
          <p>{submission.current_stage?.replaceAll("_", " ") ?? "Sin etapa activa"}</p>
        </article>
      </section>

      <section className="timeline-card">
        <div className="section-heading compact-heading">
          <span className="section-number">↳</span>
          <div>
            <h2>Etapas persistidas</h2>
            <p>Cada salida válida se reutiliza mediante una clave idempotente.</p>
          </div>
        </div>
        <ol className="stage-timeline">
          {PIPELINE_STAGES.map((stage, index) => {
            const complete = currentIndex > index || submission.status === "APPROVED";
            const active = currentIndex === index;
            return (
              <li className={complete ? "complete" : active ? "active" : ""} key={stage.state}>
                <span aria-hidden="true">{complete ? "✓" : index + 1}</span>
                <div><strong>{stage.label}</strong><small>{stage.detail}</small></div>
              </li>
            );
          })}
        </ol>
      </section>

      <Diagnostics items={[...(job?.diagnostics ?? []), ...(submission.diagnostics ?? [])]} />

      {canStart && estimate && (
        <section className="estimate-panel" aria-live="polite">
          <div>
            <span className="eyebrow">Estimación recuperada</span>
            <h2>La entrega está cargada, pero el job aún no comenzó</h2>
            <p>{estimate.estimated_model_calls} llamadas · límite superior USD {estimate.upper_bound_cost_usd.toFixed(2)} de USD {estimate.authorized_limit_usd.toFixed(2)}.</p>
          </div>
          <button className="button button-primary" disabled={!estimate.within_limit || starting} onClick={onStart} type="button">
            {starting ? "Iniciando…" : "Confirmar e iniciar pipeline"}
          </button>
        </section>
      )}

      <section className="state-legend" aria-label="Estados técnicos posibles">
        <span>Estados técnicos:</span>
        {(["QUEUED", "RUNNING", "NEEDS_REVIEW", "FAILED", "SUCCEEDED"] as const).map((status) => (
          <StatusBadge key={status} status={status} />
        ))}
      </section>

      <footer className="sticky-actions">
        <div>
          <strong>{canReview ? "Evaluación lista para revisión humana" : "El job no depende del navegador"}</strong>
          <span>{canReview ? "Abre cada pregunta junto con su evidencia exacta." : "Puedes cerrar y volver más tarde sin perder el progreso."}</span>
        </div>
        {canReview && (
          <button className="button button-primary" onClick={onOpenAssessment} type="button">
            Revisar evaluación
          </button>
        )}
      </footer>
    </div>
  );
}
