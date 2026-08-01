import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  approveAssessment,
  createExport,
  getAssessmentBundle,
  getEvidence,
  getGuide,
} from "../api/client";
import type {
  AssessmentBundle,
  EvaluationGuide,
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
    .filter(([key, value]) => key !== "kind" && value !== null && value !== undefined && value !== false)
    .map(([key, value]) => {
      const rendered = Array.isArray(value) ? value.join(", ") : String(value);
      return `${key.replaceAll("_", " ")}: ${rendered}`;
    });
  return `${locator.kind.replaceAll("_", " ")} · ${pairs.join(" · ")}`;
}

function reviewFor(question: SelectedQuestion, reviews: QuestionReview[]): QuestionReview | undefined {
  return reviews.find(
    (review) =>
      review.question_id === question.question_id || review.opportunity_id === question.opportunity_id,
  );
}

export function AssessmentReviewPage() {
  const { submissionId = "" } = useParams();
  const [bundle, setBundle] = useState<AssessmentBundle | null>(null);
  const [guide, setGuide] = useState<EvaluationGuide | null>(null);
  const [tab, setTab] = useState<"assessment" | "guide">("assessment");
  const [openedQuestions, setOpenedQuestions] = useState<Set<string>>(new Set());
  const [exports, setExports] = useState<ExportResource[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const next = await getAssessmentBundle(submissionId);
        const allEvidence = await getEvidence(submissionId);
        next.evidence = Array.from(
          new Map(
            [...next.evidence, ...allEvidence].map((item) => [item.evidence_id, item]),
          ).values(),
        );
        const nextGuide = await getGuide(next.assessment.assessment_id);
        if (!cancelled) {
          setBundle(next);
          setGuide(nextGuide);
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

  const allEvidenceOpened = useMemo(
    () =>
      Boolean(bundle?.assessment.questions.length) &&
      bundle!.assessment.questions.every((question) => openedQuestions.has(question.question_id)),
    [bundle, openedQuestions],
  );

  const approve = async () => {
    if (!bundle || !allEvidenceOpened) return;
    setBusy(true);
    setError(null);
    try {
      const approved = await approveAssessment(bundle.assessment.assessment_id, bundle.etag);
      setBundle({
        assessment: approved.assessment,
        reviews: approved.reviews.length ? approved.reviews : bundle.reviews,
        evidence: approved.evidence.length ? approved.evidence : bundle.evidence,
        etag: approved.etag,
        assessment_version: approved.assessment_version,
      });
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
      setExports((current) => [created, ...current.filter((item) => item.kind !== kind)]);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  if (!bundle || !guide) {
    return (
      <div className="content-stack">
        <section className="processing-card" aria-live="polite">
          <span className="spinner spinner-large" aria-hidden="true" />
          <h1>Preparando revisión evidence-first</h1>
          <p>Cargando evaluación, evidencia y guía como objetos separados.</p>
        </section>
        <ErrorNotice error={error} />
      </div>
    );
  }

  return (
    <AssessmentReview
      allEvidenceOpened={allEvidenceOpened}
      bundle={bundle}
      busy={busy}
      exports={exports}
      guide={guide}
      onApprove={() => void approve()}
      onEvidenceOpened={(questionId) =>
        setOpenedQuestions((current) => new Set([...current, questionId]))
      }
      onExport={(kind) => void exportView(kind)}
      onTabChange={setTab}
      tab={tab}
    >
      <ErrorNotice error={error} />
    </AssessmentReview>
  );
}

export function AssessmentReview({
  bundle,
  guide,
  tab,
  onTabChange,
  onEvidenceOpened,
  allEvidenceOpened,
  onApprove,
  onExport,
  exports,
  busy,
  children,
}: {
  bundle: AssessmentBundle;
  guide: EvaluationGuide;
  tab: "assessment" | "guide";
  onTabChange: (tab: "assessment" | "guide") => void;
  onEvidenceOpened: (questionId: string) => void;
  allEvidenceOpened: boolean;
  onApprove: () => void;
  onExport: (kind: ExportKind) => void;
  exports: ExportResource[];
  busy: boolean;
  children?: ReactNode;
}) {
  const { assessment } = bundle;
  const approved = assessment.status === "APPROVED";
  const evidenceById = useMemo(
    () => new Map(bundle.evidence.map((item) => [item.evidence_id, item])),
    [bundle.evidence],
  );

  return (
    <div className="content-stack">
      <header className="page-heading page-heading-actions">
        <div>
          <span className="eyebrow">Assessment · {assessment.subject_ref}</span>
          <h1>Revisión basada en evidencia</h1>
          <p>Cada pregunta conserva su fuente, operación y validación semántica.</p>
        </div>
        <div className="heading-actions">
          <StatusBadge status={assessment.status} />
          <span className="step-pill">3 de 3 · Revisión</span>
        </div>
      </header>

      <div className="tab-list" role="tablist" aria-label="Evaluación y guía">
        <button
          aria-selected={tab === "assessment"}
          className={tab === "assessment" ? "active" : ""}
          onClick={() => onTabChange("assessment")}
          role="tab"
          type="button"
        >
          Evaluación <span>{assessment.questions.length}</span>
        </button>
        <button
          aria-selected={tab === "guide"}
          className={tab === "guide" ? "active" : ""}
          onClick={() => onTabChange("guide")}
          role="tab"
          type="button"
        >
          Guía estructurada <span>{guide.items.length}</span>
        </button>
      </div>

      {tab === "assessment" ? (
        <div className="question-list">
          {assessment.questions.map((question, index) => {
            const review = reviewFor(question, bundle.reviews);
            return (
              <QuestionEvidenceCard
                evidenceById={evidenceById}
                index={index}
                key={question.question_id}
                onEvidenceOpened={() => onEvidenceOpened(question.question_id)}
                question={question}
                review={review}
              />
            );
          })}
          <Diagnostics items={assessment.diagnostics} />
        </div>
      ) : (
        <GuideView guide={guide} questions={assessment.questions} />
      )}

      {children}

      {approved && (
        <section className="export-panel">
          <div>
            <span className="eyebrow">Vistas derivadas</span>
            <h2>Exportar sin repetir llamadas al modelo</h2>
            <p>Los PDF y el JSON se regeneran desde los objetos canónicos ya aprobados.</p>
          </div>
          <div className="export-actions">
            {([
              ["ASSESSMENT_PDF", "Evaluación PDF"],
              ["GUIDE_PDF", "Guía PDF"],
              ["CANONICAL_JSON", "JSON canónico"],
            ] as Array<[ExportKind, string]>).map(([kind, label]) => {
              const resource = exports.find((item) => item.kind === kind);
              return resource?.download_url ? (
                <a className="button button-secondary" href={resource.download_url} key={kind} rel="noreferrer">
                  Descargar {label}
                </a>
              ) : (
                <button className="button button-secondary" disabled={busy} key={kind} onClick={() => onExport(kind)} type="button">
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
              : allEvidenceOpened
                ? "Todas las fuentes fueron abiertas; puedes aprobar el conjunto completo."
                : "Abre la fuente exacta de cada pregunta antes de aprobar."}
          </span>
        </div>
        {!approved && (
          <button className="button button-primary" disabled={!allEvidenceOpened || busy} onClick={onApprove} type="button">
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
  index,
  onEvidenceOpened,
}: {
  question: SelectedQuestion;
  review?: QuestionReview;
  evidenceById: Map<string, AssessmentBundle["evidence"][number]>;
  index: number;
  onEvidenceOpened: () => void;
}) {
  return (
    <article className="question-card">
      <header className="question-header">
        <span className="question-number">P{String(index + 1).padStart(2, "0")}</span>
        <div>
          <div className="chip-row">
            <span className="meta-chip">{question.dimension_id}</span>
            <span className="meta-chip">{question.variant_id}</span>
            <span className="operation-chip">{question.cognitive_operation.replaceAll("_", " ")}</span>
          </div>
          <h2>{question.question_text}</h2>
        </div>
        {review && <StatusBadge status={review.decision === "ACCEPT" ? "READY" : "NEEDS_REVIEW"} label={review.decision} />}
      </header>

      <div className="evidence-review-grid">
        <section className="anchor-panel">
          <span className="mini-label">Ancla y localizador</span>
          {question.anchor.fragments.map((fragment) => {
            const evidence = evidenceById.get(fragment.evidence_id);
            return (
              <blockquote key={fragment.evidence_id}>
                <p>{fragment.display_text || evidence?.content_text || "Vista protegida de la evidencia"}</p>
                <footer>
                  <code>{fragment.evidence_id}</code>
                  <span>{formatLocator(fragment.locator)}</span>
                </footer>
                {evidence?.view_url ? (
                  <a
                    className="source-link"
                    href={evidence.view_url}
                    onClick={onEvidenceOpened}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Abrir fuente exacta
                  </a>
                ) : (
                  <span className="source-unavailable">URL firmada pendiente</span>
                )}
              </blockquote>
            );
          })}
        </section>

        <section className="score-panel">
          <span className="mini-label">Scores y validación</span>
          {review ? (
            <div className="score-grid">
              {Object.entries(review.scores).map(([key, value]) => (
                <div className="score-item" key={key}>
                  <span>{SCORE_LABELS[key] ?? key.replaceAll("_", " ")}</span>
                  <strong>{Math.round(value * 100)}</strong>
                  <i><b style={{ width: `${Math.round(value * 100)}%` }} /></i>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No hay review semántica asociada.</p>
          )}
          <Diagnostics items={review?.diagnostics} />
          {review?.critical_failure_codes?.length ? (
            <div className="critical-codes">
              {review.critical_failure_codes.map((code) => <code key={code}>{code}</code>)}
            </div>
          ) : null}
        </section>
      </div>
    </article>
  );
}

function GuideView({ guide, questions }: { guide: EvaluationGuide; questions: SelectedQuestion[] }) {
  const textById = new Map(questions.map((question) => [question.question_id, question.question_text]));
  return (
    <div className="guide-list">
      {guide.items.map((item, index) => (
        <article className="guide-card" key={item.question_id}>
          <header>
            <span className="question-number">G{String(index + 1).padStart(2, "0")}</span>
            <div><h2>{textById.get(item.question_id)}</h2><p>{item.guide.purpose}</p></div>
          </header>
          <div className="guide-columns">
            <section>
              <span className="mini-label">Elementos observables</span>
              <ul>
                {item.guide.observable_elements.map((element) => (
                  <li key={element.element_id}>
                    {element.description}
                    {element.required_for_level_2 && <strong>Nivel 2</strong>}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <span className="mini-label">Alternativas aceptables</span>
              <ul>{item.guide.acceptable_alternatives.map((value) => <li key={value}>{value}</li>)}</ul>
              <span className="mini-label">No permite inferir</span>
              <ul>{item.guide.cannot_infer.map((value) => <li key={value}>{value}</li>)}</ul>
            </section>
          </div>
          <div className="level-grid">
            {item.guide.levels.map((level) => (
              <div key={level.level}>
                <span>{level.level}</span>
                <strong>{level.label}</strong>
                <p>{level.descriptor}</p>
              </div>
            ))}
          </div>
        </article>
      ))}
      <Diagnostics items={guide.diagnostics} />
    </div>
  );
}
