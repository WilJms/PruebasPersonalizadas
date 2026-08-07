import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useParams } from "wouter";
import {
  approveAssessment,
  createExport,
  getAssessmentBundle,
  getEvidence,
  verifyEvidenceFragment,
} from "../api/client";
import type {
  AssessmentBundle,
  EvaluationGuide,
  EvidenceReceipt,
  EvidenceUnit,
  ExportKind,
  ExportResource,
  QuestionReview,
  SelectedQuestion,
  SourceLocator,
} from "../api/types";
import { Diagnostics, ErrorNotice } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";

const SCORE_LABELS: Record<string, string> = {
  groundedness: "Grounding",
  anchor_sufficiency: "Suficiencia del ancla",
  criterion_relevance: "Relevancia",
  answerability: "Respondibilidad",
  cognitive_demand: "Demanda cognitiva",
  submission_specificity: "Especificidad",
  clarity: "Claridad",
  accessibility: "Accesibilidad",
  discriminative_potential: "Discriminación",
  guide_observability: "Guía observable",
};

function formatLocator(locator: SourceLocator): string {
  const pairs = Object.entries(locator)
    .filter(
      ([key, value]) =>
        key !== "kind" && value !== null && value !== undefined && value !== false,
    )
    .map(([key, value]) => {
      const rendered = Array.isArray(value) ? value.join(", ") : String(value);
      return `${key.replaceAll("_", " ")}: ${rendered}`;
    });
  return `${locator.kind.replaceAll("_", " ")} · ${pairs.join(" · ")}`;
}

function reviewFor(
  question: SelectedQuestion,
  reviews: QuestionReview[],
): QuestionReview | undefined {
  return reviews.find(
    (review) =>
      review.question_id === question.question_id ||
      review.opportunity_id === question.opportunity_id,
  );
}

function receiptFor(
  receipts: EvidenceReceipt[],
  questionId: string,
  fragmentIndex: number,
  evidenceId: string,
): EvidenceReceipt | undefined {
  return receipts.find(
    (receipt) =>
      receipt.question_id === questionId &&
      receipt.fragment_index === fragmentIndex &&
      receipt.evidence_id === evidenceId,
  );
}

function mergeEvidence(current: EvidenceUnit[], incoming: EvidenceUnit[]): EvidenceUnit[] {
  return Array.from(
    new Map([...current, ...incoming].map((item) => [item.evidence_id, item])).values(),
  );
}

export function AssessmentReviewPage() {
  const { submissionId = "" } = useParams();
  const [bundle, setBundle] = useState<AssessmentBundle | null>(null);
  const [tab, setTab] = useState<"assessment" | "guide">("assessment");
  const [exports, setExports] = useState<ExportResource[]>([]);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [next, catalog] = await Promise.all([
          getAssessmentBundle(submissionId),
          getEvidence(submissionId),
        ]);
        next.evidence = mergeEvidence(next.evidence ?? [], catalog);
        if (!cancelled) {
          setBundle(next);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) setError(caught);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [submissionId]);

  const questions = bundle?.assessment.questions ?? [];
  const receipts = bundle?.evidence_receipts ?? [];
  const allEvidenceVerified = useMemo(
    () =>
      questions.length > 0 &&
      questions.every((question) =>
        question.anchor.fragments.every((fragment, fragmentIndex) =>
          Boolean(
            receiptFor(
              receipts,
              question.question_id,
              fragmentIndex,
              fragment.evidence_id,
            ),
          ),
        ),
      ),
    [questions, receipts],
  );

  const verify = async (questionId: string, fragmentIndex: number) => {
    if (!bundle) return;
    const key = `${questionId}:${fragmentIndex}`;
    setVerifying(key);
    setError(null);
    try {
      const verification = await verifyEvidenceFragment(
        bundle.assessment.assessment_id,
        {
          assessment_version: bundle.assessment_version,
          assessment_etag: bundle.etag,
          question_id: questionId,
          fragment_index: fragmentIndex,
        },
      );
      setBundle((current) =>
        current
          ? {
              ...current,
              evidence: mergeEvidence(current.evidence ?? [], [verification.evidence]),
              evidence_receipts: [
                ...(current.evidence_receipts ?? []).filter(
                  (item) => item.receipt_id !== verification.receipt.receipt_id,
                ),
                verification.receipt,
              ],
            }
          : current,
      );
      window.open(verification.view_url, "_blank", "noopener,noreferrer");
    } catch (caught) {
      setError(caught);
    } finally {
      setVerifying(null);
    }
  };

  const approve = async () => {
    if (!bundle || !allEvidenceVerified) return;
    setBusy(true);
    setError(null);
    try {
      setBundle(await approveAssessment(bundle.assessment.assessment_id, bundle.etag));
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  const exportView = async (kind: ExportKind) => {
    if (!bundle) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createExport(bundle.assessment.assessment_id, kind);
      setExports((current) => [
        created,
        ...current.filter((item) => item.kind !== kind),
      ]);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  if (!bundle) {
    return (
      <div className="content-stack">
        <section className="processing-card" aria-live="polite">
          <span className="spinner spinner-large" aria-hidden="true" />
          <h1>Preparando revisión evidence-first</h1>
          <p>Cargando Assessment, evidencia y EvaluationGuide como objetos separados.</p>
        </section>
        <ErrorNotice error={error} />
      </div>
    );
  }

  return (
    <AssessmentReview
      allEvidenceVerified={allEvidenceVerified}
      bundle={bundle}
      busy={busy}
      exports={exports}
      onApprove={() => void approve()}
      onExport={(kind) => void exportView(kind)}
      onTabChange={setTab}
      onVerify={(questionId, fragmentIndex) => void verify(questionId, fragmentIndex)}
      tab={tab}
      verifying={verifying}
    >
      <ErrorNotice error={error} />
    </AssessmentReview>
  );
}

export function AssessmentReview({
  bundle,
  tab,
  onTabChange,
  onVerify,
  allEvidenceVerified,
  onApprove,
  onExport,
  exports,
  busy,
  verifying,
  children,
}: {
  bundle: AssessmentBundle;
  tab: "assessment" | "guide";
  onTabChange: (tab: "assessment" | "guide") => void;
  onVerify: (questionId: string, fragmentIndex: number) => void;
  allEvidenceVerified: boolean;
  onApprove: () => void;
  onExport: (kind: ExportKind) => void;
  exports: ExportResource[];
  busy: boolean;
  verifying: string | null;
  children?: ReactNode;
}) {
  const { assessment, guide } = bundle;
  const approved = assessment.status === "APPROVED";
  const questions = assessment.questions ?? [];
  const guideItems = guide.items ?? [];
  const evidence = bundle.evidence ?? [];
  const receipts = bundle.evidence_receipts ?? [];
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.evidence_id, item])),
    [evidence],
  );
  const tabsId = useId();
  const assessmentTab = `${tabsId}-assessment-tab`;
  const guideTab = `${tabsId}-guide-tab`;
  const assessmentPanel = `${tabsId}-assessment-panel`;
  const guidePanel = `${tabsId}-guide-panel`;
  const assessmentRef = useRef<HTMLButtonElement>(null);
  const guideRef = useRef<HTMLButtonElement>(null);

  const changeTabFromKeyboard = (event: KeyboardEvent<HTMLButtonElement>) => {
    let next: "assessment" | "guide" | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      next = tab === "assessment" ? "guide" : "assessment";
    } else if (event.key === "Home") {
      next = "assessment";
    } else if (event.key === "End") {
      next = "guide";
    }
    if (!next) return;
    event.preventDefault();
    onTabChange(next);
    (next === "assessment" ? assessmentRef : guideRef).current?.focus();
  };

  const choiceContractsComplete = questions.every((question) => {
    if (question.response_format !== "CHOICE") return true;
    const choices = question.choices ?? [];
    return (
      choices.length >= 3 &&
      choices.filter((option) => option.is_best_answer).length === 1 &&
      choices.every(
        (option) => option.evaluator_rationale && (option.is_best_answer || option.misconception),
      )
    );
  });

  return (
    <div className="content-stack">
      <header className="page-heading page-heading-actions">
        <div>
          <span className="eyebrow">Assessment · {assessment.subject_ref}</span>
          <h1>Revisión basada en evidencia</h1>
          <p>Cada fragmento se verifica contra bytes sellados antes de habilitar la aprobación.</p>
        </div>
        <div className="heading-actions">
          <StatusBadge status={assessment.status} />
          <span className="step-pill">3 de 3 · Revisión</span>
        </div>
      </header>

      <div className="tab-list" role="tablist" aria-label="Evaluación y guía">
        <button
          aria-controls={assessmentPanel}
          aria-selected={tab === "assessment"}
          className={tab === "assessment" ? "active" : ""}
          id={assessmentTab}
          onClick={() => onTabChange("assessment")}
          onKeyDown={changeTabFromKeyboard}
          ref={assessmentRef}
          role="tab"
          tabIndex={tab === "assessment" ? 0 : -1}
          type="button"
        >
          Evaluación <span>{questions.length}</span>
        </button>
        <button
          aria-controls={guidePanel}
          aria-selected={tab === "guide"}
          className={tab === "guide" ? "active" : ""}
          id={guideTab}
          onClick={() => onTabChange("guide")}
          onKeyDown={changeTabFromKeyboard}
          ref={guideRef}
          role="tab"
          tabIndex={tab === "guide" ? 0 : -1}
          type="button"
        >
          Guía estructurada <span>{guideItems.length}</span>
        </button>
      </div>

      <section
        aria-labelledby={assessmentTab}
        hidden={tab !== "assessment"}
        id={assessmentPanel}
        role="tabpanel"
        tabIndex={0}
      >
        <div className="question-list">
          {questions.map((question, index) => (
            <QuestionEvidenceCard
              evidenceById={evidenceById}
              index={index}
              key={question.question_id}
              onVerify={onVerify}
              question={question}
              receipts={receipts}
              review={reviewFor(question, bundle.reviews)}
              verifying={verifying}
            />
          ))}
          <Diagnostics items={assessment.diagnostics} />
        </div>
      </section>

      <section
        aria-labelledby={guideTab}
        hidden={tab !== "guide"}
        id={guidePanel}
        role="tabpanel"
        tabIndex={0}
      >
        <GuideView guide={guide} questions={questions} />
      </section>

      {!choiceContractsComplete && (
        <div className="error-notice" role="alert">
          Una pregunta CHOICE no contiene alternativas evaluables completas. La aprobación permanece bloqueada.
        </div>
      )}
      {children}

      {approved && (
        <section className="export-panel">
          <div>
            <span className="eyebrow">Vistas derivadas</span>
            <h2>Exportar sin repetir llamadas al modelo</h2>
            <p>Los PDF y el JSON se regeneran desde objetos canónicos ya aprobados.</p>
          </div>
          <div className="export-actions">
            {([
              ["ASSESSMENT_PDF", "Evaluación PDF"],
              ["GUIDE_PDF", "Guía PDF"],
              ["CANONICAL_JSON", "JSON canónico"],
            ] as Array<[ExportKind, string]>).map(([kind, label]) => {
              const resource = exports.find((item) => item.kind === kind);
              return resource?.download_url ? (
                <a
                  className="button button-secondary"
                  href={resource.download_url}
                  key={kind}
                  rel="noreferrer"
                >
                  Descargar {label}
                </a>
              ) : (
                <button
                  className="button button-secondary"
                  disabled={busy}
                  key={kind}
                  onClick={() => onExport(kind)}
                  type="button"
                >
                  {resource?.status === "QUEUED" ? `Preparando ${label}…` : label}
                </button>
              );
            })}
          </div>
        </section>
      )}

      <footer className="sticky-actions">
        <div>
          <strong>{approved ? "Assessment aprobado" : "Revisión humana obligatoria"}</strong>
          <span>
            {approved
              ? "La versión aprobada quedó congelada."
              : allEvidenceVerified
                ? "Todos los fragmentos tienen confirmación durable para tu identidad."
                : "Carga y verifica el localizador exacto de cada fragmento antes de aprobar."}
          </span>
        </div>
        {!approved && (
          <button
            className="button button-primary"
            disabled={!allEvidenceVerified || !choiceContractsComplete || busy}
            onClick={onApprove}
            type="button"
          >
            Aprobar Assessment
          </button>
        )}
      </footer>
    </div>
  );
}

function QuestionEvidenceCard({
  question,
  review,
  evidenceById,
  receipts,
  index,
  onVerify,
  verifying,
}: {
  question: SelectedQuestion;
  review?: QuestionReview;
  evidenceById: Map<string, EvidenceUnit>;
  receipts: EvidenceReceipt[];
  index: number;
  onVerify: (questionId: string, fragmentIndex: number) => void;
  verifying: string | null;
}) {
  const choices = question.choices ?? [];
  const preliminary = question.preliminary_guide;
  return (
    <article className="question-card">
      <header className="question-header">
        <span className="question-number">P{String(index + 1).padStart(2, "0")}</span>
        <div>
          <div className="chip-row">
            <span className="meta-chip">{question.response_format.replaceAll("_", " ")}</span>
            <span className="meta-chip">Dificultad derivada · {question.difficulty}</span>
            <span className="meta-chip">{question.estimated_minutes} min</span>
            <span className="meta-chip">Planning · {Math.round(question.planning_score * 100)}%</span>
            <span className="operation-chip">{question.cognitive_operation.replaceAll("_", " ")}</span>
          </div>
          <h2>{question.question_text}</h2>
          <p className="muted">
            Justificación estudiantil: {question.student_justification_required ? "requerida" : "no requerida"}
          </p>
        </div>
        {review && (
          <StatusBadge
            status={review.decision === "ACCEPT" ? "READY" : "NEEDS_REVIEW"}
            label={review.decision}
          />
        )}
      </header>

      {question.response_format === "CHOICE" && (
        <div className="choice-review-grid">
          <section>
            <span className="mini-label">Contenido del estudiante</span>
            <ol className="choice-list">
              {choices.map((choice) => <li key={choice.option_id}>{choice.text}</li>)}
            </ol>
          </section>
          <section className="evaluator-only">
            <span className="mini-label">Información del evaluador</span>
            {choices.map((choice) => (
              <div className="choice-rationale" key={choice.option_id}>
                <strong>{choice.is_best_answer ? "Mejor respuesta" : "Distractor"} · {choice.option_id}</strong>
                <p>{choice.evaluator_rationale}</p>
                {!choice.is_best_answer && <p>Posible error conceptual: {choice.misconception}</p>}
              </div>
            ))}
          </section>
        </div>
      )}

      <div className="evidence-review-grid">
        <section className="anchor-panel">
          <span className="mini-label">Ancla y localizador</span>
          {question.anchor.fragments.map((fragment, fragmentIndex) => {
            const evidence = evidenceById.get(fragment.evidence_id);
            const receipt = receiptFor(
              receipts,
              question.question_id,
              fragmentIndex,
              fragment.evidence_id,
            );
            const key = `${question.question_id}:${fragmentIndex}`;
            return (
              <blockquote key={`${fragment.evidence_id}:${fragmentIndex}`}>
                <p>{fragment.display_text || evidence?.content_text || "Vista protegida de la evidencia"}</p>
                <footer>
                  <code>{fragment.evidence_id}</code>
                  <span>{formatLocator(fragment.locator)}</span>
                  <span>{fragment.transformation.replaceAll("_", " ")}</span>
                </footer>
                {receipt ? (
                  <span className="source-verified">Fuente cargada y localizador verificado</span>
                ) : (
                  <button
                    className="source-link"
                    disabled={verifying === key}
                    onClick={() => onVerify(question.question_id, fragmentIndex)}
                    type="button"
                  >
                    {verifying === key ? "Verificando…" : "Cargar y verificar fuente exacta"}
                  </button>
                )}
              </blockquote>
            );
          })}
        </section>

        <section className="score-panel">
          <span className="mini-label">Scores y validación semántica</span>
          {review ? (
            <>
              <div className="chip-row">
                <span className="meta-chip">Dificultad revisada · {review.estimated_difficulty}</span>
                <span className="meta-chip">{review.estimated_minutes} min</span>
                <span className="meta-chip">Confianza · {Math.round(review.confidence * 100)}%</span>
              </div>
              <div className="score-grid">
                {Object.entries(review.scores).map(([key, value]) => (
                  <div className="score-item" key={key}>
                    <span>{SCORE_LABELS[key] ?? key.replaceAll("_", " ")}</span>
                    <strong>{Math.round(value * 100)}</strong>
                    <i><b style={{ width: `${Math.round(value * 100)}%` }} /></i>
                  </div>
                ))}
              </div>
              {(review.justifications ?? []).map((value) => <p key={value}>{value}</p>)}
              <ReferenceList label="Evidencia de review" values={review.evidence_ids ?? []} />
              <ReferenceList label="Fuentes de curso" values={review.source_ids ?? []} emptyLabel="Sin fuentes de curso: contexto CLOSED." />
            </>
          ) : (
            <p className="muted">No hay review semántica asociada.</p>
          )}
          <Diagnostics items={review?.diagnostics} />
          {(review?.critical_failure_codes ?? []).length > 0 && (
            <div className="critical-codes">
              {(review?.critical_failure_codes ?? []).map((code) => <code key={code}>{code}</code>)}
            </div>
          )}
        </section>
      </div>

      <details className="technical-details">
        <summary>Trazabilidad técnica y guía preliminar</summary>
        <ReferenceList
          label="Identidades"
          values={[
            `question: ${question.question_id}`,
            `candidate: ${question.source_candidate_id}`,
            `opportunity: ${question.opportunity_id}`,
            `template: ${question.opportunity_template_id}`,
            `dimension: ${question.dimension_id}`,
            `variant: ${question.variant_id}`,
          ]}
        />
        <ReferenceList label="Evidence IDs" values={question.evidence_ids} />
        <ReferenceList label="Course source IDs" values={question.course_source_ids ?? []} emptyLabel="Vacío por diseño en contexto CLOSED." />
        <ReferenceList
          label="Citas"
          values={(question.citations ?? []).map((citation) => `${citation.source_id} · ${citation.locator}`)}
          emptyLabel="Sin citas de curso en contexto CLOSED."
        />
        <div className="preliminary-guide">
          <strong>Guía preliminar de generación (no es la EvaluationGuide final)</strong>
          <p>{preliminary.purpose}</p>
        </div>
      </details>
    </article>
  );
}

function ReferenceList({
  label,
  values,
  emptyLabel = "Sin referencias.",
}: {
  label: string;
  values: string[];
  emptyLabel?: string;
}) {
  return (
    <div className="reference-list">
      <span className="mini-label">{label}</span>
      {values.length ? (
        <ul>{values.map((value) => <li key={value}><code>{value}</code></li>)}</ul>
      ) : (
        <p className="muted">{emptyLabel}</p>
      )}
    </div>
  );
}

function GuideView({
  guide,
  questions,
}: {
  guide: EvaluationGuide;
  questions: SelectedQuestion[];
}) {
  const textById = new Map(
    questions.map((question) => [question.question_id, question.question_text]),
  );
  return (
    <div className="guide-list">
      {(guide.items ?? []).map((item, index) => (
        <article className="guide-card" key={item.question_id}>
          <header>
            <span className="question-number">G{String(index + 1).padStart(2, "0")}</span>
            <div><h2>{textById.get(item.question_id)}</h2><p>{item.guide.purpose}</p></div>
          </header>
          <div className="guide-columns">
            <section>
              <span className="mini-label">Elementos observables</span>
              <ul>
                {(item.guide.observable_elements ?? []).map((element) => (
                  <li key={element.element_id}>
                    <strong>{element.description}</strong>
                    {element.required_for_level_2 && <span>Nivel 2 requerido</span>}
                    <ReferenceList label="Evidence IDs" values={element.evidence_ids} />
                    <ReferenceList label="Source IDs" values={element.source_ids ?? []} emptyLabel="Vacío en contexto CLOSED." />
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <ReferenceList label="Alternativas aceptables" values={item.guide.acceptable_alternatives ?? []} />
              <ReferenceList label="Posibles errores conceptuales a observar" values={item.guide.misconceptions ?? []} />
              <ReferenceList label="No permite inferir" values={item.guide.cannot_infer ?? []} />
            </section>
          </div>
          <div className="level-grid">
            {(item.guide.levels ?? []).map((level) => (
              <div key={level.level}>
                <span>{level.level}</span>
                <strong>{level.label}</strong>
                <p>{level.descriptor}</p>
                <ReferenceList label="Observables" values={level.observable_element_ids ?? []} />
              </div>
            ))}
          </div>
        </article>
      ))}
      <Diagnostics items={guide.diagnostics} />
    </div>
  );
}
