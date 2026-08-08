import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "wouter";
import {
  approveBlueprint,
  createPolicyDecision,
  generateBlueprint,
  getActivity,
  getActivityAmbiguity,
  getJob,
  getLatestBlueprint,
  updateBlueprint,
} from "../api/client";
import type {
  AmbiguityView,
  AssessmentBlueprint,
  BlueprintOpportunity,
  BlueprintVariant,
  BlueprintView,
  JobStatus,
} from "../api/types";
import { Diagnostics, ErrorNotice } from "../components/Feedback";
import { JobControlPanel } from "../components/JobControlPanel";
import { StatusBadge } from "../components/StatusBadge";
import { useRouteState } from "../routing";

interface RouteState {
  jobId?: string;
}

function cloneBlueprint(blueprint: AssessmentBlueprint): AssessmentBlueprint {
  return JSON.parse(JSON.stringify(blueprint)) as AssessmentBlueprint;
}

function percentage(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function AmbiguityResolution({
  view,
  job,
  busy,
  error,
  onResolve,
}: {
  view: AmbiguityView;
  job: JobStatus | null;
  busy: boolean;
  error: unknown;
  onResolve: (selections: Record<string, string>, notes: Record<string, string>) => void;
}) {
  const persistedSelections = useMemo(
    () =>
      Object.fromEntries(
        view.decisions.map((decision) => [decision.issue_id, decision.selected_option_id]),
      ),
    [view.decisions],
  );
  const [selections, setSelections] = useState<Record<string, string>>(persistedSelections);
  const [notes, setNotes] = useState<Record<string, string>>({});

  useEffect(() => setSelections(persistedSelections), [persistedSelections]);

  const blockingResolved = (view.report.issues ?? [])
    .filter((issue) => issue.blocking)
    .every((issue) => Boolean(selections[issue.issue_id]));

  return (
    <div className="content-stack">
      <header className="page-heading page-heading-actions">
        <div>
          <span className="eyebrow">P03 · decisión docente</span>
          <h1>Confirma las ambigüedades de la actividad</h1>
          <p>La evidencia queda visible y ninguna opción se decide automáticamente.</p>
        </div>
        <div className="heading-actions">
          <StatusBadge status={job?.status ?? "NEEDS_REVIEW"} />
          <span className="step-pill">1 de 3 · Actividad</span>
        </div>
      </header>

      <div className="ambiguity-list">
        {(view.report.issues ?? []).map((issue, issueIndex) => {
          const persisted = view.decisions.some((decision) => decision.issue_id === issue.issue_id);
          return (
            <article className="ambiguity-card" key={issue.issue_id}>
              <header>
                <span className="dimension-index">A{String(issueIndex + 1).padStart(2, "0")}</span>
                <div>
                  <div className="chip-row">
                    <StatusBadge status={issue.severity} label={issue.severity} />
                    {issue.blocking && <span className="meta-chip">Bloqueante</span>}
                    {persisted && <span className="meta-chip">Decisión guardada</span>}
                  </div>
                  <h2>{issue.issue_code.replaceAll("_", " ")}</h2>
                  <p>{issue.explanation}</p>
                </div>
              </header>

              <div className="ambiguity-evidence" aria-label="Evidencia vinculada">
                <span className="mini-label">Evidencia que originó la duda</span>
                {(issue.evidence_ids ?? []).length ? (
                  <div className="chip-row">
                    {(issue.evidence_ids ?? []).map((evidenceId) => <code key={evidenceId}>{evidenceId}</code>)}
                  </div>
                ) : (
                  <span className="muted">Hallazgo de reglas sobre la consigna completa.</span>
                )}
              </div>

              <fieldset className="decision-options">
                <legend>Selecciona una interpretación</legend>
                {issue.options.map((option) => (
                  <label className="decision-option" key={option.option_id}>
                    <input
                      checked={selections[issue.issue_id] === option.option_id}
                      disabled={persisted}
                      name={`decision-${issue.issue_id}`}
                      onChange={() =>
                        setSelections((current) => ({
                          ...current,
                          [issue.issue_id]: option.option_id,
                        }))
                      }
                      type="radio"
                      value={option.option_id}
                    />
                    <span>
                      <strong>
                        {option.label}
                        {option.option_id === issue.recommended_option_id && <em>Recomendada</em>}
                      </strong>
                      <small>{option.consequence}</small>
                    </span>
                  </label>
                ))}
              </fieldset>

              {!persisted && (
                <label className="field">
                  <span>Nota docente <em>opcional</em></span>
                  <textarea
                    maxLength={2000}
                    onChange={(event) =>
                      setNotes((current) => ({ ...current, [issue.issue_id]: event.target.value }))
                    }
                    placeholder="Registra el criterio usado, sin datos personales."
                    rows={2}
                    value={notes[issue.issue_id] ?? ""}
                  />
                </label>
              )}
            </article>
          );
        })}
      </div>

      <ErrorNotice error={error} />
      <footer className="sticky-actions">
        <div>
          <strong>{blockingResolved ? "Decisiones listas" : "Faltan decisiones bloqueantes"}</strong>
          <span>Al continuar, el pipeline reutiliza salidas válidas y vuelve a construir la versión revisable.</span>
        </div>
        <button
          className="button button-primary"
          disabled={!blockingResolved || busy}
          onClick={() => onResolve(selections, notes)}
          type="button"
        >
          {busy ? "Guardando decisiones…" : "Guardar y reanudar blueprint"}
        </button>
      </footer>
    </div>
  );
}

export function BlueprintPage() {
  const { activityId = "" } = useParams();
  const [, navigate] = useLocation();
  const [view, setView] = useState<BlueprintView | null>(null);
  const [ambiguity, setAmbiguity] = useState<AmbiguityView | null>(null);
  const [draft, setDraft] = useState<AssessmentBlueprint | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [activityStatus, setActivityStatus] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [recoveringActivity, setRecoveringActivity] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const routeState = useRouteState<RouteState>();
  const [activeJobId, setActiveJobId] = useState(routeState?.jobId);

  const loadBlueprint = useCallback(async () => {
    const loaded = await getLatestBlueprint(activityId);
    setView(loaded);
    setDraft(cloneBlueprint(loaded.blueprint));
    setError(null);
    return loaded;
  }, [activityId]);

  const loadAmbiguity = useCallback(async () => {
    const loaded = await getActivityAmbiguity(activityId);
    setAmbiguity(loaded);
    setError(null);
    return loaded;
  }, [activityId]);

  useEffect(() => {
    let cancelled = false;
    const initialLoad = async () => {
      setLoading(true);
      try {
        await loadBlueprint();
      } catch (caught) {
        if (!activeJobId && !cancelled) {
          try {
            const activity = await getActivity(activityId);
            setActivityStatus(activity.status);
            if (activity.status === "NEEDS_REVIEW") {
              await loadAmbiguity();
            } else if (["QUEUED", "RUNNING"].includes(activity.status)) {
              setRecoveringActivity(true);
              setError(null);
            } else {
              setError(caught);
            }
          } catch (recoveryError) {
            if (!cancelled) setError(recoveryError);
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void initialLoad();
    return () => {
      cancelled = true;
    };
  }, [activeJobId, loadAmbiguity, loadBlueprint]);

  useEffect(() => {
    if (!recoveringActivity || view || ambiguity || activeJobId) return;
    let cancelled = false;
    let timer: number | undefined;
    const recover = async () => {
      try {
        const activity = await getActivity(activityId);
        if (cancelled) return;
        setActivityStatus(activity.status);
        if (activity.status === "NEEDS_REVIEW") {
          await loadAmbiguity();
          setRecoveringActivity(false);
          return;
        }
        if (activity.status === "TECHNICAL_FAILURE") {
          setRecoveringActivity(false);
          setError(new Error("El pipeline de actividad terminó con un fallo técnico."));
          return;
        }
        try {
          await loadBlueprint();
          setRecoveringActivity(false);
          return;
        } catch {
          timer = window.setTimeout(() => void recover(), 1800);
        }
      } catch (caught) {
        if (!cancelled) setError(caught);
      }
    };
    void recover();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeJobId, activityId, ambiguity, loadAmbiguity, loadBlueprint, recoveringActivity, view]);

  useEffect(() => {
    if (!activeJobId || view || ambiguity) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await getJob(activeJobId);
        if (cancelled) return;
        setJob(next);
        if (next.status === "SUCCEEDED") {
          await loadBlueprint();
          return;
        }
        if (next.status === "NEEDS_REVIEW") {
          await loadAmbiguity();
          return;
        }
        if (next.status === "FAILED") return;
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
  }, [activeJobId, ambiguity, loadAmbiguity, loadBlueprint, view]);

  const resolveAmbiguity = async (
    selections: Record<string, string>,
    notes: Record<string, string>,
  ) => {
    if (!ambiguity) return;
    setSaving(true);
    setError(null);
    try {
      const resolvedIssueIds = new Set(ambiguity.decisions.map((item) => item.issue_id));
      for (const issue of ambiguity.report.issues ?? []) {
        const selectedOptionId = selections[issue.issue_id];
        if (!selectedOptionId || resolvedIssueIds.has(issue.issue_id)) continue;
        await createPolicyDecision(activityId, {
          issue_id: issue.issue_id,
          selected_option_id: selectedOptionId,
          ...(notes[issue.issue_id]?.trim() ? { note: notes[issue.issue_id].trim() } : {}),
        });
      }
      const operation = await generateBlueprint(activityId);
      setAmbiguity(null);
      setView(null);
      setDraft(null);
      setJob(null);
      setActivityStatus("QUEUED");
      setActiveJobId(operation.job_id);
    } catch (caught) {
      setError(caught);
    } finally {
      setSaving(false);
    }
  };

  const criticalFailure = useMemo(
    () => view?.review?.checks?.some((check) => check.critical && check.status === "FAIL") ?? false,
    [view],
  );

  const updateDimension = (dimensionId: string, field: "name" | "justification", value: string) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            dimensions: current.dimensions.map((dimension) =>
              dimension.dimension_id === dimensionId ? { ...dimension, [field]: value } : dimension,
            ),
          }
        : current,
    );
  };

  const updateVariant = (
    dimensionId: string,
    variantId: string,
    field: keyof Pick<BlueprintVariant, "name" | "description">,
    value: string,
  ) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            dimensions: current.dimensions.map((dimension) =>
              dimension.dimension_id !== dimensionId
                ? dimension
                : {
                    ...dimension,
                    evidence_variants: dimension.evidence_variants.map((variant) =>
                      variant.variant_id === variantId ? { ...variant, [field]: value } : variant,
                    ),
                  },
            ),
          }
        : current,
    );
  };

  const updateOpportunity = (
    dimensionId: string,
    variantId: string,
    opportunityId: string,
    field: keyof Pick<BlueprintOpportunity, "focus" | "observable">,
    value: string,
  ) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            dimensions: current.dimensions.map((dimension) =>
              dimension.dimension_id !== dimensionId
                ? dimension
                : {
                    ...dimension,
                    evidence_variants: dimension.evidence_variants.map((variant) =>
                      variant.variant_id !== variantId
                        ? variant
                        : {
                            ...variant,
                            question_opportunities: variant.question_opportunities.map((opportunity) =>
                              opportunity.opportunity_template_id === opportunityId
                                ? { ...opportunity, [field]: value }
                                : opportunity,
                            ),
                          },
                    ),
                  },
            ),
          }
        : current,
    );
  };

  const save = async () => {
    if (!view || !draft) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateBlueprint(activityId, draft, view.etag);
      setView(updated);
      setDraft(cloneBlueprint(updated.blueprint));
      setEditing(false);
    } catch (caught) {
      setError(caught);
    } finally {
      setSaving(false);
    }
  };

  const approve = async () => {
    if (!view) return;
    setSaving(true);
    setError(null);
    try {
      const approved = await approveBlueprint(activityId, view.blueprint, view.etag);
      setView(approved);
      setDraft(cloneBlueprint(approved.blueprint));
      setEditing(false);
    } catch (caught) {
      setError(caught);
    } finally {
      setSaving(false);
    }
  };

  if (ambiguity) {
    return (
      <AmbiguityResolution
        busy={saving}
        error={error}
        job={job}
        onResolve={(selections, notes) => void resolveAmbiguity(selections, notes)}
        view={ambiguity}
      />
    );
  }

  if (loading || recoveringActivity || (!view && job && !["FAILED", "NEEDS_REVIEW"].includes(job.status))) {
    return (
      <div className="content-stack">
        <header className="page-heading">
          <div>
            <span className="eyebrow">Pipeline de actividad</span>
            <h1>Construyendo el blueprint</h1>
            <p>P01–P05 están normalizando fuentes y revisando el catálogo común.</p>
          </div>
          <StatusBadge status={job?.status ?? "RUNNING"} />
        </header>
        <section className="processing-card" aria-live="polite">
          <span className="spinner spinner-large" aria-hidden="true" />
          <h2>{job?.stage ? job.stage.replaceAll("_", " ") : "Recuperando pipeline durable"}</h2>
          <div aria-label="Progreso del pipeline de actividad" aria-valuemax={100} aria-valuemin={0} aria-valuenow={Math.round((job?.progress ?? 0.08) * 100)} className="progress-track" role="progressbar">
            <span style={{ width: `${Math.round((job?.progress ?? 0.08) * 100)}%` }} />
          </div>
          <p>Esta vista se actualizará cuando la versión sea revisable.</p>
        </section>
        <ErrorNotice error={error} />
        {job && <JobControlPanel jobId={job.job_id} onChange={(next) => { setJob(next.job); setActiveJobId(next.job.job_id); }} />}
      </div>
    );
  }

  const terminalStatus = job?.status ?? activityStatus;
  if (!view && ["FAILED", "NEEDS_REVIEW", "TECHNICAL_FAILURE"].includes(terminalStatus ?? "")) {
    return (
      <div className="content-stack">
        <header className="page-heading page-heading-actions">
          <div>
            <span className="eyebrow">Pipeline de actividad</span>
            <h1>
              {terminalStatus === "NEEDS_REVIEW"
                ? "La actividad requiere revisión"
                : "El pipeline no pudo completar el blueprint"}
            </h1>
            <p>
              {terminalStatus === "NEEDS_REVIEW"
                ? "No hay una decisión P03 accionable disponible; revisa los diagnósticos persistidos."
                : "El estado terminal quedó guardado y no se oculta detrás de una carga indefinida."}
            </p>
          </div>
          <StatusBadge status={terminalStatus ?? "FAILED"} />
        </header>
        <Diagnostics items={job?.diagnostics} />
        <ErrorNotice error={error} />
        {job && <JobControlPanel jobId={job.job_id} onChange={(next) => { setJob(next.job); setActiveJobId(next.job.job_id); }} />}
      </div>
    );
  }

  if (!view || !draft) {
    return (
      <div className="content-stack">
        <ErrorNotice error={error ?? new Error("El blueprint todavía no está disponible.")} />
      </div>
    );
  }

  const blueprint = editing ? draft : view.blueprint;
  const approved = blueprint.status === "APPROVED";
  const reviewReady = !view.review || view.review.status === "READY";

  return (
    <div className="content-stack">
      <header className="page-heading page-heading-actions">
        <div>
          <span className="eyebrow">Blueprint · versión {blueprint.blueprint_version}</span>
          <h1>Catálogo de comprensión revisable</h1>
          <p>Las dimensiones comparables se instanciarán después con la evidencia de la entrega.</p>
        </div>
        <div className="heading-actions">
          <StatusBadge status={blueprint.status} />
          <span className="etag" title="Control de concurrencia">ETag {view.etag}</span>
        </div>
      </header>

      <section className="summary-strip" aria-label="Resumen del blueprint">
        <div><span>Dimensiones</span><strong>{blueprint.dimensions.length}</strong></div>
        <div>
          <span>Variantes</span>
          <strong>{blueprint.dimensions.reduce((sum, item) => sum + item.evidence_variants.length, 0)}</strong>
        </div>
        <div>
          <span>Oportunidades</span>
          <strong>
            {blueprint.dimensions.reduce(
              (sum, item) =>
                sum + item.evidence_variants.reduce((variantSum, variant) => variantSum + variant.question_opportunities.length, 0),
              0,
            )}
          </strong>
        </div>
        <div><span>Preguntas por entrega</span><strong>{blueprint.assessment_constraints.question_count}</strong></div>
      </section>

      <section className="form-card blueprint-constraints">
        <div className="section-heading compact-heading">
          <span className="section-number">C</span>
          <div><h2>Restricciones globales</h2><p>La dificultad no se selecciona: se deriva por oportunidad.</p></div>
        </div>
        <dl className="activity-summary">
          <div><dt>Contexto</dt><dd>{blueprint.context_mode}</dd></div>
          <div><dt>Tiempo objetivo</dt><dd>{blueprint.assessment_constraints.target_total_minutes} min</dd></div>
          <div><dt>Calidad mínima</dt><dd>{percentage(blueprint.assessment_constraints.minimum_opportunity_quality)}</dd></div>
          <div><dt>Reserva máxima</dt><dd>{blueprint.assessment_constraints.max_reserve_opportunities}</dd></div>
          <div><dt>Justificación</dt><dd>{blueprint.assessment_constraints.structured_justification_policy.mode}</dd></div>
          <div><dt>Formatos</dt><dd>{blueprint.assessment_constraints.allowed_response_formats.join(", ")}</dd></div>
        </dl>
        <div className="reference-list">
          <span className="mini-label">Templates con justificación seleccionada</span>
          {(blueprint.assessment_constraints.structured_justification_policy.selected_opportunity_template_ids ?? []).length ? (
            <div className="chip-row">{(blueprint.assessment_constraints.structured_justification_policy.selected_opportunity_template_ids ?? []).map((id) => <code key={id}>{id}</code>)}</div>
          ) : <p className="muted">No aplica a esta política.</p>}
        </div>
        <div className="reference-list"><span className="mini-label">Decisiones docentes vinculadas</span>{(blueprint.decision_ids ?? []).length ? <div className="chip-row">{(blueprint.decision_ids ?? []).map((id) => <code key={id}>{id}</code>)}</div> : <p className="muted">Sin decisiones adicionales.</p>}</div>
      </section>

      {view.review && (
        <section className="review-banner">
          <div>
            <span className="eyebrow">Revisión P05</span>
            <h2>{view.review.approval_recommendation?.replaceAll("_", " ") ?? "Requiere revisión"}</h2>
          </div>
          <div className="review-checks">
            {(view.review.checks ?? []).map((check) => (
              <span className={`review-check check-${check.status.toLowerCase()}`} key={check.check_code}>
                {check.status} · {check.category.replaceAll("_", " ")}
              </span>
            ))}
          </div>
          <div className="review-check-details">
            {(view.review.checks ?? []).map((check) => (
              <article key={check.check_code}>
                <header><code>{check.check_code}</code><StatusBadge status={check.status === "FAIL" ? "ERROR" : check.status === "WARN" ? "WARNING" : "READY"} label={check.status} />{check.critical && <strong>Crítico</strong>}</header>
                <p>{check.message}</p>
                {(check.referenced_ids ?? []).length > 0 && <div className="chip-row">{(check.referenced_ids ?? []).map((id) => <code key={id}>{id}</code>)}</div>}
                {check.correction && <p><strong>Corrección:</strong> {check.correction}</p>}
              </article>
            ))}
          </div>
        </section>
      )}

      <Diagnostics items={[...(view.issues ?? []), ...(blueprint.diagnostics ?? []), ...(view.review?.diagnostics ?? [])]} />

      <div className="blueprint-list">
        {blueprint.dimensions.map((dimension, dimensionIndex) => (
          <article className="dimension-card" key={dimension.dimension_id}>
            <header>
              <span className="dimension-index">D{String(dimensionIndex + 1).padStart(2, "0")}</span>
              <div className="dimension-title">
                {editing ? (
                  <input
                    aria-label={`Nombre de dimensión ${dimensionIndex + 1}`}
                    onChange={(event) => updateDimension(dimension.dimension_id, "name", event.target.value)}
                    value={dimension.name}
                  />
                ) : (
                  <h2>{dimension.name}</h2>
                )}
                {editing ? (
                  <textarea
                    aria-label={`Justificación de dimensión ${dimensionIndex + 1}`}
                    onChange={(event) => updateDimension(dimension.dimension_id, "justification", event.target.value)}
                    rows={2}
                    value={dimension.justification}
                  />
                ) : (
                  <p>{dimension.justification}</p>
                )}
              </div>
              <div className="priority-meter">
                <span>Prioridad</span>
                <strong>{percentage(dimension.verification_priority)}</strong>
                <i><b style={{ width: percentage(dimension.verification_priority) }} /></i>
              </div>
            </header>

            <div className="dimension-metadata">
              <div><span className="mini-label">Criterios</span><div className="chip-row">{dimension.criterion_ids.map((id) => <code key={id}>{id}</code>)}</div></div>
              <div><span className="mini-label">Resultados de aprendizaje</span>{(dimension.learning_outcome_ids ?? []).length ? <div className="chip-row">{(dimension.learning_outcome_ids ?? []).map((id) => <code key={id}>{id}</code>)}</div> : <span className="muted">Sin referencias adicionales</span>}</div>
              <div><span className="mini-label">Peso</span><strong>{dimension.grading_weight == null ? "No informado" : percentage(dimension.grading_weight)}</strong></div>
              <dl className="factor-grid">
                {Object.entries(dimension.factors).map(([name, value]) => <div key={name}><dt>{name.replaceAll("_", " ")}</dt><dd>{percentage(value)}</dd></div>)}
              </dl>
            </div>

            <div className="variant-list">
              {dimension.evidence_variants.map((variant, variantIndex) => (
                <section className="variant-card" key={variant.variant_id}>
                  <div className="variant-heading">
                    <span>Variante {variantIndex + 1}</span>
                    {editing ? (
                      <input
                        aria-label={`Nombre de variante ${variantIndex + 1}`}
                        onChange={(event) =>
                          updateVariant(dimension.dimension_id, variant.variant_id, "name", event.target.value)
                        }
                        value={variant.name}
                      />
                    ) : (
                      <h3>{variant.name}</h3>
                    )}
                    {editing ? (
                      <textarea
                        aria-label={`Descripción de variante ${variantIndex + 1}`}
                        onChange={(event) =>
                          updateVariant(dimension.dimension_id, variant.variant_id, "description", event.target.value)
                        }
                        rows={2}
                        value={variant.description}
                      />
                    ) : (
                      <p>{variant.description}</p>
                    )}
                  </div>

                  <div className="variant-requirement">
                    <span className="mini-label">Requisito de evidencia</span>
                    <dl className="activity-summary">
                      <div><dt>Modalidades</dt><dd>{variant.evidence_requirement.allowed_modalities.join(", ")}</dd></div>
                      <div><dt>Unidades distintas</dt><dd>{variant.evidence_requirement.min_distinct_units}</dd></div>
                      <div><dt>Confianza mínima</dt><dd>{percentage(variant.evidence_requirement.min_extraction_confidence)}</dd></div>
                      <div><dt>Alineación mínima</dt><dd>{percentage(variant.evidence_requirement.min_alignment)}</dd></div>
                      <div><dt>Cross-artifact</dt><dd>{variant.evidence_requirement.cross_artifact_required ? "Sí" : "No"}</dd></div>
                      <div><dt>Fuentes de curso</dt><dd>{variant.evidence_requirement.course_sources_allowed ? "Permitidas" : "No permitidas"}</dd></div>
                      <div><dt>Potencial</dt><dd>{percentage(variant.verification_potential)}</dd></div>
                    </dl>
                  </div>

                  <div className="supported-operations">
                    <span className="mini-label">Operaciones soportadas</span>
                    <div className="chip-row">
                      {variant.supported_operations.map((operation) => (
                        <details className="operation-detail" key={operation.cognitive_operation}>
                          <summary className="operation-chip">{operation.cognitive_operation.replaceAll("_", " ")} <em>{percentage(operation.support_strength)}</em></summary>
                          <p>{operation.rationale}</p>
                        </details>
                      ))}
                    </div>
                  </div>

                  <div className="opportunity-table">
                    <div className="opportunity-header">
                      <span>Catálogo de oportunidades</span>
                      <span>Operación</span>
                      <span>Tiempo</span>
                    </div>
                    {variant.question_opportunities.map((opportunity) => (
                      <div className="opportunity-row" key={opportunity.opportunity_template_id}>
                        <div>
                          {editing ? (
                            <>
                              <input
                                aria-label={`Foco ${opportunity.opportunity_template_id}`}
                                onChange={(event) =>
                                  updateOpportunity(
                                    dimension.dimension_id,
                                    variant.variant_id,
                                    opportunity.opportunity_template_id,
                                    "focus",
                                    event.target.value,
                                  )
                                }
                                value={opportunity.focus}
                              />
                              <textarea
                                aria-label={`Observable ${opportunity.opportunity_template_id}`}
                                onChange={(event) =>
                                  updateOpportunity(
                                    dimension.dimension_id,
                                    variant.variant_id,
                                    opportunity.opportunity_template_id,
                                    "observable",
                                    event.target.value,
                                  )
                                }
                                rows={2}
                                value={opportunity.observable}
                              />
                            </>
                          ) : (
                            <>
                              <strong>{opportunity.focus}</strong>
                              <span>{opportunity.observable}</span>
                              <div className="chip-row">
                                <span className="meta-chip">Dificultad derivada · {opportunity.difficulty}</span>
                                <span className="meta-chip">Calidad mínima · {percentage(opportunity.minimum_quality)}</span>
                                <span className="meta-chip">Potencial · {percentage(opportunity.verification_potential)}</span>
                                <span className="meta-chip">Justificación · {opportunity.student_justification_required ? "sí" : "no"}</span>
                              </div>
                              <small>Anclas: {opportunity.allowed_anchor_structures.join(", ")}</small>
                              <small>Formatos: {opportunity.allowed_response_formats.join(", ")}</small>
                              <code>{opportunity.opportunity_template_id}</code>
                            </>
                          )}
                        </div>
                        <span>{opportunity.cognitive_operation.replaceAll("_", " ")}</span>
                        <span>{opportunity.target_minutes} min</span>
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </article>
        ))}
      </div>

      <ErrorNotice error={error} />
      <footer className="sticky-actions">
        <div>
          <strong>{approved ? "Blueprint congelado" : editing ? "Edición en curso" : "Versión revisable"}</strong>
          <span>
            {approved
              ? "Las entregas usarán esta versión inmutable."
              : "Los cambios se guardan como una versión nueva con control ETag."}
          </span>
        </div>
        <div>
          {!approved && !editing && (
            <button className="button button-secondary" onClick={() => setEditing(true)} type="button">
              Editar blueprint
            </button>
          )}
          {editing && (
            <>
              <button
                className="button button-quiet"
                onClick={() => {
                  setDraft(cloneBlueprint(view.blueprint));
                  setEditing(false);
                }}
                type="button"
              >
                Descartar
              </button>
              <button className="button button-primary" disabled={saving} onClick={() => void save()} type="button">
                Guardar nueva versión
              </button>
            </>
          )}
          {!approved && !editing && (
            <button
              className="button button-primary"
              disabled={saving || criticalFailure || !reviewReady}
              onClick={() => void approve()}
              type="button"
            >
              Aprobar blueprint
            </button>
          )}
          {approved && (
            <button
              className="button button-primary"
              onClick={() => navigate(`/activities/${activityId}/submissions`)}
              type="button"
            >
              Abrir lote de entregas
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}
