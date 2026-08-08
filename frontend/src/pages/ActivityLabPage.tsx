import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "wouter";
import {
  bulkApproveAssessments,
  createFeedback,
  createSubmissionBatch,
  getAssessmentBundle,
  getActivityCoverage,
  getActivityMetrics,
  getSubmissionEstimate,
  listActivityFeedback,
  listActivitySubmissions,
  listBulkApprovalHistory,
  runSubmission,
  uploadSubmissionArtifact,
} from "../api/client";
import type {
  BulkApprovalRecord,
  CostEstimate,
  CoverageReport,
  ExperimentMetrics,
  FeedbackCategory,
  FeedbackEvent,
  FeedbackRating,
  Stage2Submission,
} from "../api/types";
import { Diagnostics, ErrorNotice } from "../components/Feedback";
import { LimitedEvidenceWarning } from "../components/LimitedEvidenceWarning";
import { RovingTabs } from "../components/RovingTabs";
import { StatusBadge } from "../components/StatusBadge";

const SUBMISSION_ACCEPT =
  ".pdf,.docx,.txt,.md,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

type LabTab = "submissions" | "coverage" | "metrics" | "feedback";

function parseSubjectRefs(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function numeric(value: number | null | undefined, suffix = ""): string {
  return value === null || value === undefined ? "—" : `${value.toLocaleString("es-CL")}${suffix}`;
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").toLocaleLowerCase("es-CL");
}

export function ActivityLabPage() {
  const { activityId = "" } = useParams();
  const [tab, setTab] = useState<LabTab>("submissions");
  const [submissions, setSubmissions] = useState<Stage2Submission[]>([]);
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);
  const [metrics, setMetrics] = useState<ExperimentMetrics | null>(null);
  const [feedback, setFeedback] = useState<FeedbackEvent[]>([]);
  const [bulkHistory, setBulkHistory] = useState<BulkApprovalRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    const [submissionResult, coverageResult, metricsResult, feedbackResult, bulkResult] =
      await Promise.allSettled([
        listActivitySubmissions(activityId),
        getActivityCoverage(activityId),
        getActivityMetrics(activityId),
        listActivityFeedback(activityId),
        listBulkApprovalHistory(activityId),
      ]);
    if (submissionResult.status === "fulfilled") {
      const hydrated = await Promise.all(
        submissionResult.value.map(async (item) => {
          if (!item.assessment_id || item.assessment_version) return item;
          try {
            const bundle = await getAssessmentBundle(item.submission_id);
            return { ...item, assessment_version: bundle.assessment_version };
          } catch {
            return item;
          }
        }),
      );
      setSubmissions(hydrated);
    }
    if (coverageResult.status === "fulfilled") setCoverage(coverageResult.value);
    if (metricsResult.status === "fulfilled") setMetrics(metricsResult.value);
    if (feedbackResult.status === "fulfilled") setFeedback(feedbackResult.value);
    if (bulkResult.status === "fulfilled") setBulkHistory(bulkResult.value);
    const rejected = [submissionResult, coverageResult, metricsResult, feedbackResult, bulkResult].find(
      (result) => result.status === "rejected",
    );
    setError(rejected?.status === "rejected" ? rejected.reason : null);
    setLoading(false);
  }, [activityId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="content-stack">
      <header className="page-heading page-heading-actions">
        <div>
          <span className="eyebrow">Entorno experimental · Etapa 2</span>
          <h1>Lote de entregas</h1>
          <p>Procesa, compara y revisa cada entrega con estados independientes.</p>
        </div>
        <Link className="button button-secondary" to={`/activities/${activityId}/submission`}>
          Alta individual
        </Link>
      </header>

      <LimitedEvidenceWarning />
      <ErrorNotice error={error} />
      {loading && <p className="inline-status" aria-live="polite">Actualizando datos del lote…</p>}

      <RovingTabs
        label="Paneles del lote experimental"
        onChange={setTab}
        tabs={[
          {
            key: "submissions",
            label: <>Entregas <span>{submissions.length}</span></>,
            panel: (
              <SubmissionsPanel
                activityId={activityId}
                bulkHistory={bulkHistory}
                onChange={setSubmissions}
                onError={setError}
                onReload={reload}
                submissions={submissions}
              />
            ),
          },
          {
            key: "coverage",
            label: "Cobertura",
            panel: <CoveragePanel report={coverage} />,
          },
          {
            key: "metrics",
            label: "Métricas",
            panel: <MetricsPanel metrics={metrics} />,
          },
          {
            key: "feedback",
            label: <>Feedback <span>{feedback.length}</span></>,
            panel: (
              <FeedbackPanel
                activityId={activityId}
                items={feedback}
                onCreated={(item) => setFeedback((current) => [item, ...current])}
                onError={setError}
              />
            ),
          },
        ]}
        value={tab}
      />
    </div>
  );
}

function SubmissionsPanel({
  activityId,
  bulkHistory,
  submissions,
  onChange,
  onReload,
  onError,
}: {
  activityId: string;
  bulkHistory: BulkApprovalRecord[];
  submissions: Stage2Submission[];
  onChange: (items: Stage2Submission[]) => void;
  onReload: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [subjectRefs, setSubjectRefs] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("ALL");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  const [estimates, setEstimates] = useState<Record<string, CostEstimate | undefined>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkApprovalRecord | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const announcementRef = useRef<HTMLDivElement>(null);
  const refs = parseSubjectRefs(subjectRefs);
  const invalidRefs = refs.filter((value) => !/^[a-z][a-z0-9_-]{2,127}$/.test(value));
  const statuses = useMemo(
    () => Array.from(new Set(submissions.map((item) => item.status))).sort(),
    [submissions],
  );
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("es-CL");
    return submissions.filter(
      (item) =>
        (status === "ALL" || item.status === status) &&
        (!normalized || item.subject_ref.toLocaleLowerCase("es-CL").includes(normalized)),
    );
  }, [query, status, submissions]);
  const selectedTargets = submissions
    .filter((item) => item.assessment_id && item.assessment_version && selected.has(item.submission_id))
    .map((item) => ({
      assessment_id: item.assessment_id as string,
      assessment_version: item.assessment_version as number,
    }));

  const createBatch = async (event: FormEvent) => {
    event.preventDefault();
    if (!refs.length || invalidRefs.length) return;
    setBatchBusy(true);
    onError(null);
    try {
      const created = await createSubmissionBatch(activityId, refs);
      const byId = new Map(submissions.map((item) => [item.submission_id, item]));
      created.submissions.forEach((item) => byId.set(item.submission_id, item));
      onChange(Array.from(byId.values()));
      setSubjectRefs("");
      setAnnouncement(`${created.submissions.length} entregas quedaron preparadas.`);
    } catch (caught) {
      onError(caught);
      setAnnouncement("No se pudo preparar el lote.");
    } finally {
      setBatchBusy(false);
      announcementRef.current?.focus();
    }
  };

  const upload = async (submission: Stage2Submission) => {
    const file = files[submission.submission_id];
    if (!file) return;
    setBusyId(submission.submission_id);
    onError(null);
    try {
      await uploadSubmissionArtifact(submission.submission_id, file);
      setFiles((current) => {
        const next = { ...current };
        delete next[submission.submission_id];
        return next;
      });
      setAnnouncement(`Archivo de ${submission.subject_ref} cargado.`);
      await onReload();
    } catch (caught) {
      onError(caught);
    } finally {
      setBusyId(null);
    }
  };

  const run = async (submission: Stage2Submission) => {
    if (!estimates[submission.submission_id]?.within_limit) return;
    setBusyId(submission.submission_id);
    onError(null);
    try {
      await runSubmission(submission.submission_id);
      setAnnouncement(`Pipeline de ${submission.subject_ref} iniciado.`);
      await onReload();
    } catch (caught) {
      onError(caught);
    } finally {
      setBusyId(null);
    }
  };

  const estimate = async (submission: Stage2Submission) => {
    setBusyId(submission.submission_id);
    onError(null);
    try {
      const next = await getSubmissionEstimate(submission.submission_id);
      setEstimates((current) => ({ ...current, [submission.submission_id]: next }));
      setAnnouncement(`Estimación de ${submission.subject_ref} preparada para confirmación.`);
    } catch (caught) {
      onError(caught);
    } finally {
      setBusyId(null);
    }
  };

  const bulkApprove = async () => {
    if (!confirmed || !selectedTargets.length) return;
    setBatchBusy(true);
    onError(null);
    try {
      const result = await bulkApproveAssessments(activityId, selectedTargets);
      setBulkResult(result);
      setAnnouncement(
        `${(result.approved_targets ?? []).length} assessments aprobados; ${(result.excluded_targets ?? []).length} excluidos.`,
      );
      setSelected(new Set());
      setConfirmed(false);
      await onReload();
    } catch (caught) {
      onError(caught);
    } finally {
      setBatchBusy(false);
      announcementRef.current?.focus();
    }
  };

  return (
    <div className="lab-panel content-stack">
      <div aria-live="polite" className="sr-focus-status" ref={announcementRef} tabIndex={-1}>
        {announcement}
      </div>
      <form className="batch-create-card" onSubmit={(event) => void createBatch(event)}>
        <div>
          <span className="eyebrow">Alta manual seudónima</span>
          <h2>Preparar lote</h2>
          <p>Una referencia por línea o separada por comas. No uses nombres ni correos.</p>
        </div>
        <label className="field">
          <span>Referencias seudónimas</span>
          <textarea
            aria-describedby="batch-subject-help"
            aria-invalid={invalidRefs.length > 0}
            name="subject_refs"
            onChange={(event) => setSubjectRefs(event.target.value)}
            placeholder={"estudiante_014\nestudiante_015"}
            required
            rows={4}
            value={subjectRefs}
          />
          <small id="batch-subject-help">{invalidRefs.length ? `${invalidRefs.length} referencias no cumplen el formato seudónimo.` : `${refs.length} referencias únicas listas.`}</small>
        </label>
        <button className="button button-primary" disabled={!refs.length || invalidRefs.length > 0 || batchBusy} type="submit">
          {batchBusy ? "Preparando…" : "Crear entregas del lote"}
        </button>
      </form>

      <section className="batch-table-card" aria-labelledby="submissions-title">
        <div className="section-heading compact-heading">
          <span className="section-number">{filtered.length}</span>
          <div><h2 id="submissions-title">Estados por entrega</h2><p>Los fallos y avances no se propagan entre filas.</p></div>
        </div>
        <div className="batch-toolbar">
          <label className="field compact-field">
            <span>Buscar referencia</span>
            <input onChange={(event) => setQuery(event.target.value)} type="search" value={query} />
          </label>
          <label className="field compact-field">
            <span>Filtrar por estado</span>
            <select onChange={(event) => setStatus(event.target.value)} value={status}>
              <option value="ALL">Todos</option>
              {statuses.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
            </select>
          </label>
          <button className="button button-quiet" onClick={() => void onReload()} type="button">
            Actualizar
          </button>
        </div>

        <div className="table-scroll" tabIndex={0} aria-label="Tabla desplazable de entregas">
          <table className="batch-table">
            <caption className="visually-hidden">Entregas y acciones independientes</caption>
            <thead><tr><th scope="col">Elegir</th><th scope="col">Referencia</th><th scope="col">Dominio</th><th scope="col">Progreso</th><th scope="col">Archivo DOCX/PDF/TXT/MD</th><th scope="col">Acciones</th></tr></thead>
            <tbody>
              {filtered.map((item) => {
                const processing = busyId === item.submission_id;
                return (
                  <tr key={item.submission_id}>
                    <td>
                      <input
                        aria-label={`Seleccionar assessment de ${item.subject_ref}`}
                        checked={selected.has(item.submission_id)}
                        disabled={!item.assessment_id || !item.assessment_version}
                        onChange={(event) => setSelected((current) => {
                          const next = new Set(current);
                          if (event.target.checked) next.add(item.submission_id);
                          else next.delete(item.submission_id);
                          return next;
                        })}
                        type="checkbox"
                        title={!item.assessment_version ? "La versión exacta aún no está disponible" : undefined}
                      />
                    </td>
                    <th scope="row"><strong>{item.subject_ref}</strong><code>{item.submission_id}</code></th>
                    <td><StatusBadge status={item.status} /></td>
                    <td>
                      <span>{Math.round(item.progress * 100)}%</span>
                      <div aria-label={`Progreso ${Math.round(item.progress * 100)}%`} aria-valuemax={100} aria-valuemin={0} aria-valuenow={Math.round(item.progress * 100)} className="progress-track compact-progress" role="progressbar"><span style={{ width: `${Math.round(item.progress * 100)}%` }} /></div>
                    </td>
                    <td>
                      {!item.artifact_uploaded && item.progress === 0 && !item.active_job_id && !item.assessment_id ? (
                        <label className="compact-upload">
                          <span>Elegir archivo para {item.subject_ref}</span>
                          <input accept={SUBMISSION_ACCEPT} onChange={(event) => setFiles((current) => ({ ...current, [item.submission_id]: event.target.files?.[0] }))} type="file" />
                        </label>
                      ) : (
                        <span className="source-verified">Archivo persistido</span>
                      )}
                    </td>
                    <td><div className="row-actions">
                      {files[item.submission_id] && item.progress === 0 && (
                        <button className="button button-secondary" disabled={processing} onClick={() => void upload(item)} type="button">Cargar</button>
                      )}
                      {item.status === "UPLOADED" && !item.active_job_id && (
                        estimates[item.submission_id] ? (
                          <><span className="row-estimate">Máx. USD {estimates[item.submission_id]?.upper_bound_cost_usd.toFixed(2)}</span><button className="button button-primary" disabled={processing || !estimates[item.submission_id]?.within_limit} onClick={() => void run(item)} type="button">Confirmar e iniciar</button></>
                        ) : (
                          <button className="button button-primary" disabled={processing} onClick={() => void estimate(item)} type="button">Estimar</button>
                        )
                      )}
                      <Link className="button button-quiet" to={`/submissions/${item.submission_id}`}>Ver estado</Link>
                      {item.assessment_id && <Link className="button button-quiet" to={`/submissions/${item.submission_id}/review`}>Revisar</Link>}
                    </div></td>
                  </tr>
                );
              })}
              {!filtered.length && <tr><td colSpan={6}>No hay entregas que coincidan con el filtro.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="bulk-approval-card" aria-labelledby="bulk-title">
        <div><span className="eyebrow">Acción de alto impacto</span><h2 id="bulk-title">Aprobación masiva</h2><p>Solo se envían las versiones exactas seleccionadas. Las excepciones permanecen en revisión individual.</p></div>
        <strong>{selectedTargets.length} assessments seleccionados</strong>
        <label className="confirmation-check">
          <input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" />
          <span>Confirmo la aprobación de todos los assessments elegibles seleccionados.</span>
        </label>
        <button className="button button-primary" disabled={!confirmed || !selectedTargets.length || batchBusy} onClick={() => void bulkApprove()} type="button">
          Aprobar selección confirmada
        </button>
        {bulkResult && <BulkResultView result={bulkResult} />}
        <BulkApprovalHistory items={bulkHistory} />
      </section>
    </div>
  );
}

function BulkResultView({ result }: { result: BulkApprovalRecord }) {
  return (
    <div className="bulk-result" aria-live="polite">
      <section><h3>Aprobados ({(result.approved_targets ?? []).length})</h3><ul>{(result.approved_targets ?? []).map((item) => <li key={`${item.assessment_id}:${item.assessment_version}`}><code>{item.assessment_id}</code> · v{item.assessment_version}</li>)}</ul></section>
      <section><h3>Excluidos ({(result.excluded_targets ?? []).length})</h3><ul>{(result.excluded_targets ?? []).map((item) => <li key={`${item.target.assessment_id}:${item.target.assessment_version}`}><code>{item.target.assessment_id}</code> · {item.reason_code}: {item.message}</li>)}</ul></section>
    </div>
  );
}

function BulkApprovalHistory({ items }: { items: BulkApprovalRecord[] }) {
  if (!items.length) return <p className="muted bulk-history-empty">Aún no hay aprobaciones masivas persistidas.</p>;
  return (
    <div className="table-scroll bulk-history" tabIndex={0} aria-label="Historial de aprobaciones masivas">
      <table className="batch-table"><caption>Historial durable de aprobación masiva</caption><thead><tr><th scope="col">Approval ID</th><th scope="col">Solicitados</th><th scope="col">Aprobados</th><th scope="col">Excluidos</th><th scope="col">Fecha</th></tr></thead><tbody>{items.map((item) => <tr key={item.approval_id}><th scope="row"><code>{item.approval_id}</code></th><td>{item.requested_targets.length}</td><td>{(item.approved_targets ?? []).length}</td><td>{(item.excluded_targets ?? []).length}</td><td>{new Date(item.approved_at).toLocaleString("es-CL")}</td></tr>)}</tbody></table>
    </div>
  );
}

export function CoveragePanel({ report }: { report: CoverageReport | null }) {
  if (!report) return <section className="empty-state"><h2>Sin reporte de cobertura</h2><p>Se mostrará cuando existan salidas verificables.</p></section>;
  return (
    <section className="lab-panel content-stack" aria-labelledby="coverage-title">
      <header><span className="eyebrow">Reporte {report.scope}</span><h2 id="coverage-title">Cobertura trazable</h2><p>Generado {new Date(report.generated_at).toLocaleString("es-CL")}.</p></header>
      <div className="metric-grid">
        {report.summary.map((item) => <article className="metric-card" key={item.dimension_id}><span>{item.dimension_id}</span><strong>{numeric(item.selected_opportunity_count)} / {numeric(item.available_opportunity_count)}</strong><small>{item.evidence_unit_count} unidades · {item.reused_variant_count} variantes reutilizadas</small></article>)}
      </div>
      <div className="table-scroll" tabIndex={0} aria-label="Trazas de cobertura">
        <table className="batch-table coverage-table"><caption className="visually-hidden">Trazas completas de oportunidades a evidencia</caption><thead><tr><th scope="col">Entrega</th><th scope="col">Dimensión / criterios</th><th scope="col">Variante / oportunidad</th><th scope="col">Evidence IDs</th><th scope="col">Operación</th><th scope="col">Plan</th><th scope="col">Resultado</th><th scope="col">Diagnóstico</th></tr></thead><tbody>{(report.traces ?? []).map((trace) => <tr key={`${trace.submission_id}:${trace.opportunity_id}`}><th scope="row"><code>{trace.submission_id}</code></th><td><strong>{trace.dimension_id}</strong><small>{(trace.criterion_ids ?? []).join(", ") || "Sin criterios"}</small></td><td><strong>{trace.variant_id}</strong><small>{trace.opportunity_id}</small></td><td>{(trace.evidence_ids ?? []).join(", ") || "—"}</td><td>{humanize(trace.cognitive_operation)}</td><td>{humanize(trace.planning_role)}{trace.reused_variant ? " · variante reutilizada" : ""}</td><td>{humanize(trace.outcome)}</td><td>{(trace.failure_code ?? trace.exclusion_reason_code ?? (trace.diagnostics ?? []).map((item) => item.code).join(", ")) || "—"}</td></tr>)}</tbody></table>
      </div>
      <Diagnostics items={report.diagnostics} />
    </section>
  );
}

export function MetricsPanel({ metrics }: { metrics: ExperimentMetrics | null }) {
  if (!metrics) return <section className="empty-state"><h2>Sin métricas todavía</h2><p>Las métricas aparecen sin exponer texto estudiantil.</p></section>;
  return (
    <section className="lab-panel content-stack" aria-labelledby="metrics-title">
      <header><span className="eyebrow">Observabilidad separada</span><h2 id="metrics-title">Métricas experimentales</h2><p>No interpretes un score del sistema como probabilidad sobre el estudiante.</p></header>
      <div className="metrics-groups">
        <MetricGroup title="Técnicas" items={[["Jobs", metrics.technical.job_count], ["Exitosos", metrics.technical.succeeded_count], ["Fallidos", metrics.technical.failed_count], ["Cancelados", metrics.technical.cancelled_count], ["Retries", metrics.technical.retry_count], ["Latencia p95", metrics.technical.latency_p95_ms, " ms"], ["Tokens entrada", metrics.technical.input_tokens], ["Tokens cacheados", metrics.technical.cached_input_tokens], ["Tokens salida", metrics.technical.output_tokens], ["Costo estimado", metrics.technical.estimated_cost_usd, " USD"], ["Costo real", metrics.technical.actual_cost_usd, " USD"]]} />
        <MetricGroup title="Calidad del sistema" items={[["Assessments", metrics.quality.assessment_count], ["Fail closed", metrics.quality.fail_closed_count], ["Defectos", metrics.quality.defect_count], ["Planes exactos", metrics.quality.exact_plan_count], ["Reemplazos", metrics.quality.replacement_count]]} />
        <MetricGroup title="Revisión humana" items={[["Preguntas revisadas", metrics.human_review.reviewed_question_count], ["Aceptadas", metrics.human_review.accepted_count], ["Editadas", metrics.human_review.edited_count], ["Rechazadas", metrics.human_review.rejected_count], ["Regeneradas", metrics.human_review.regenerated_count], ["Tiempo", metrics.human_review.review_seconds, " s"]]} />
      </div>
      {(metrics.by_stage ?? []).length > 0 && <div className="table-scroll" tabIndex={0} aria-label="Métricas por etapa"><table className="batch-table"><caption>Métricas técnicas por etapa</caption><thead><tr><th scope="col">Etapa</th><th scope="col">Runs</th><th scope="col">Éxito</th><th scope="col">Fallo</th><th scope="col">Cancelado</th><th scope="col">Retries</th><th scope="col">p50 / p95</th></tr></thead><tbody>{(metrics.by_stage ?? []).map((item) => <tr key={item.stage}><th scope="row">{humanize(item.stage)}</th><td>{item.runs}</td><td>{item.succeeded}</td><td>{item.failed}</td><td>{item.cancelled}</td><td>{item.retries}</td><td>{item.latency_p50_ms} / {item.latency_p95_ms} ms</td></tr>)}</tbody></table></div>}
      {(metrics.by_model ?? []).length > 0 && <div className="table-scroll" tabIndex={0} aria-label="Métricas por ruta y modelo"><table className="batch-table"><caption>Métricas agregadas por ruta y snapshot de modelo</caption><thead><tr><th scope="col">Ruta</th><th scope="col">Modelo</th><th scope="col">Llamadas / errores</th><th scope="col">Tokens E/C/S</th><th scope="col">Costo estimado / real</th><th scope="col">p50 / p95</th></tr></thead><tbody>{(metrics.by_model ?? []).map((item) => <tr key={`${item.route_id}:${item.model_snapshot}`}><th scope="row"><code>{item.route_id}</code></th><td>{item.provider} · {item.model_snapshot}</td><td>{item.call_count} / {item.error_count}</td><td>{item.input_tokens} / {item.cached_input_tokens} / {item.output_tokens}</td><td>{item.estimated_cost_usd.toFixed(4)} / {item.actual_cost_usd.toFixed(4)} USD</td><td>{item.latency_p50_ms} / {item.latency_p95_ms} ms</td></tr>)}</tbody></table></div>}
    </section>
  );
}

function MetricGroup({ title, items }: { title: string; items: Array<[string, number | null | undefined, string?]> }) {
  return <section className="metric-group"><h3>{title}</h3><dl>{items.map(([label, value, suffix]) => <div key={label}><dt>{label}</dt><dd>{numeric(value, suffix)}</dd></div>)}</dl></section>;
}

function FeedbackPanel({ activityId, items, onCreated, onError }: { activityId: string; items: FeedbackEvent[]; onCreated: (item: FeedbackEvent) => void; onError: (error: unknown) => void }) {
  const [category, setCategory] = useState<FeedbackCategory>("WORKFLOW");
  const [rating, setRating] = useState<FeedbackRating>("NEUTRAL");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    onError(null);
    try {
      const created = await createFeedback({ activity_id: activityId, target_type: "ACTIVITY", category, rating, comment: comment.trim() || undefined });
      onCreated(created);
      setComment("");
      setSaved("Feedback guardado por separado de cualquier decisión académica.");
    } catch (caught) {
      onError(caught);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lab-panel feedback-layout">
      <form className="feedback-card" onSubmit={(event) => void submit(event)}>
        <span className="eyebrow">Feedback gobernable</span><h2>Registrar experiencia docente</h2><p>No se convierte automáticamente en training data ni en una decisión académica.</p>
        <label className="field"><span>Categoría</span><select onChange={(event) => setCategory(event.target.value as FeedbackCategory)} value={category}><option value="GROUNDING">Grounding</option><option value="ANSWERABILITY">Respondibilidad</option><option value="QUESTION_QUALITY">Calidad de preguntas</option><option value="GUIDE_QUALITY">Calidad de guía</option><option value="COVERAGE">Cobertura</option><option value="WORKFLOW">Flujo de trabajo</option><option value="EXPORT">Exportación</option><option value="OTHER">Otro</option></select></label>
        <fieldset className="rating-field"><legend>Valoración</legend>{([['VERY_UNHELPFUL', 'Muy poco útil'], ['UNHELPFUL', 'Poco útil'], ['NEUTRAL', 'Neutral'], ['HELPFUL', 'Útil'], ['VERY_HELPFUL', 'Muy útil']] as Array<[FeedbackRating, string]>).map(([value, label]) => <label key={value}><input checked={rating === value} name="rating" onChange={() => setRating(value)} type="radio" value={value} /><span>{label}</span></label>)}</fieldset>
        <label className="field"><span>Comentario opcional</span><textarea maxLength={1000} onChange={(event) => setComment(event.target.value)} rows={4} value={comment} /></label>
        <button className="button button-primary" disabled={busy} type="submit">{busy ? "Guardando…" : "Guardar feedback"}</button>
        <p aria-live="polite">{saved}</p>
      </form>
      <section className="feedback-history" aria-labelledby="feedback-history-title"><h2 id="feedback-history-title">Historial</h2>{items.length ? <ol>{items.map((item) => <li key={item.feedback_id}><header><strong>{humanize(item.category)}</strong><span>{humanize(item.rating)}</span></header><p>{item.comment || "Sin comentario"}</p><small>{new Date(item.created_at).toLocaleString("es-CL")}</small></li>)}</ol> : <p>No hay feedback registrado.</p>}</section>
    </div>
  );
}
