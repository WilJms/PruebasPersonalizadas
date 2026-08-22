import {
  type FormEvent,
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
  createFeedback,
  createExport,
  getAssessmentBundle,
  getEvidence,
  getSubmissionCoverage,
  listExports,
  listQuestionActions,
  reviewQuestion,
  verifyEvidenceFragment,
} from "../api/client";
import type {
  AssessmentBundle,
  EvaluationGuide,
  EvidenceReceipt,
  EvidenceUnit,
  ExportDownloadResource,
  ExportRecord,
  ExportKind,
  ExportResource,
  CoverageReport,
  FeedbackCategory,
  FeedbackRating,
  JobStatus,
  QuestionReviewActionInput,
  QuestionReviewActionRecord,
  QuestionReview,
  SelectedQuestion,
  SourceLocator,
} from "../api/types";
import { Diagnostics, ErrorNotice } from "../components/Feedback";
import { JobControlPanel } from "../components/JobControlPanel";
import { LimitedEvidenceWarning } from "../components/LimitedEvidenceWarning";
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
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [downloads, setDownloads] = useState<Array<ExportResource | ExportDownloadResource>>([]);
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);
  const [actionHistory, setActionHistory] = useState<Record<string, QuestionReviewActionRecord[]>>({});
  const [actionJobs, setActionJobs] = useState<Record<string, JobStatus[]>>({});
  const [busy, setBusy] = useState(false);
  const [questionBusy, setQuestionBusy] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState("");
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const actionMessageRef = useRef<HTMLDivElement>(null);
  const [verifying, setVerifying] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const next = await getAssessmentBundle(submissionId);
        const [catalog, nextCoverage, exportHistory, actionEntries] = await Promise.all([
          getEvidence(submissionId),
          getSubmissionCoverage(submissionId).catch(() => null),
          listExports(next.assessment.assessment_id).catch(() => []),
          Promise.all((next.assessment.questions ?? []).map(async (question) => [
            question.question_id,
            await listQuestionActions(next.assessment.assessment_id, question.question_id).catch(() => ({ items: [], jobs: [] })),
          ] as const)),
        ]);
        next.evidence = mergeEvidence(next.evidence ?? [], catalog);
        if (!cancelled) {
          setBundle(next);
          setCoverage(nextCoverage);
          setExports(exportHistory);
          setActionHistory(Object.fromEntries(
            actionEntries.map(([questionId, result]) => [questionId, result.items]),
          ));
          setActionJobs(Object.fromEntries(
            actionEntries.map(([questionId, result]) => [questionId, result.jobs]),
          ));
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

  const guideLifecycle = bundle?.guide_status ?? "NOT_AVAILABLE";
  useEffect(() => {
    if (
      bundle?.assessment.status !== "APPROVED" ||
      !["PENDING", "BUILDING"].includes(guideLifecycle)
    ) {
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const pollGuide = async () => {
      try {
        const refreshed = await getAssessmentBundle(submissionId);
        if (!cancelled) {
          setBundle((current) => ({
            ...refreshed,
            evidence: mergeEvidence(
              refreshed.evidence ?? [],
              current?.evidence ?? [],
            ),
          }));
          if (["PENDING", "BUILDING"].includes(refreshed.guide_status)) {
            timer = window.setTimeout(pollGuide, 1_500);
          }
        }
      } catch (caught) {
        if (!cancelled) setError(caught);
      }
    };
    timer = window.setTimeout(pollGuide, 1_500);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [bundle?.assessment.status, guideLifecycle, submissionId]);

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
        created.record,
        ...current.filter((item) => item.export_id !== created.record.export_id),
      ]);
      setDownloads((current) => [
        created.export,
        ...created.downloads,
        ...current.filter((item) => item.kind !== kind),
      ]);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  const actOnQuestion = async (
    question: SelectedQuestion,
    input: QuestionReviewActionInput,
  ) => {
    if (!bundle) return;
    setQuestionBusy(question.question_id);
    setError(null);
    setActionMessage("");
    try {
      const result = await reviewQuestion(
        bundle.assessment.assessment_id,
        question.question_id,
        input,
        bundle.etag,
      );
      const actionJob = result.job;
      if (
        actionJob &&
        (!result.record || ["QUEUED", "RUNNING"].includes(actionJob.status))
      ) {
        setActionJobs((current) => ({
          ...current,
          [question.question_id]: [
            actionJob,
            ...(current[question.question_id] ?? []).filter(
              (job) => job.job_id !== actionJob.job_id,
            ),
          ],
        }));
      }
      if (!result.record) {
        if (result.bundle) {
          setBundle({
            ...result.bundle,
            etag: result.etag ?? result.bundle.etag,
            evidence: mergeEvidence(result.bundle.evidence ?? [], bundle.evidence ?? []),
          });
        }
        const waiting = actionJob && ["QUEUED", "RUNNING"].includes(actionJob.status);
        setActionMessage(waiting
          ? `REGENERATE quedó en cola para ${question.question_id}. Copia el job ID y ejecútalo con autorización independiente.`
          : `REGENERATE no fue aplicado a ${question.question_id}; revisa el estado durable del job.`);
        if (!waiting) {
          setError(new Error("El job de regeneración terminó antes de aplicar una nueva pregunta."));
        }
        window.setTimeout(() => actionMessageRef.current?.focus(), 0);
        return;
      }
      if (result.record.status === "FAILED") {
        const failedRecord = result.record;
        setActionHistory((current) => ({
          ...current,
          [question.question_id]: [failedRecord, ...(current[question.question_id] ?? [])],
        }));
        if (result.bundle) {
          setBundle({
            ...result.bundle,
            etag: result.etag ?? result.bundle.etag,
            evidence: mergeEvidence(result.bundle.evidence ?? [], bundle.evidence ?? []),
          });
        }
        const codes = (result.record.diagnostics ?? []).map((item) => item.code).join(", ");
        setError(new Error(`La revalidación localizada falló${codes ? ` (${codes})` : ""}. La versión anterior se conserva.`));
        setActionMessage(`${input.action} no fue aplicado a ${question.question_id}; la revalidación falló y quedó registrada.`);
        window.setTimeout(() => actionMessageRef.current?.focus(), 0);
        return;
      }
      if (result.bundle) {
        setBundle({
          ...result.bundle,
          etag: result.etag ?? result.bundle.etag,
          evidence: mergeEvidence(result.bundle.evidence ?? [], bundle.evidence ?? []),
        });
      } else {
        const refreshed = await getAssessmentBundle(submissionId);
        refreshed.evidence = mergeEvidence(refreshed.evidence ?? [], bundle.evidence ?? []);
        setBundle(refreshed);
      }
      const appliedRecord = result.record;
      setActionHistory((current) => ({
        ...current,
        [question.question_id]: [appliedRecord, ...(current[question.question_id] ?? [])],
      }));
      setActionMessage(
        `${input.action} aplicado a ${question.question_id}; la versión y revalidación quedaron registradas.`,
      );
      window.setTimeout(() => actionMessageRef.current?.focus(), 0);
    } catch (caught) {
      setError(caught);
      setActionMessage(`No se pudo aplicar ${input.action} a ${question.question_id}.`);
      window.setTimeout(() => actionMessageRef.current?.focus(), 0);
    } finally {
      setQuestionBusy(null);
    }
  };

  const saveReviewFeedback = async (input: {
    questionId?: string;
    category: FeedbackCategory;
    rating: FeedbackRating;
    comment?: string;
  }) => {
    if (!bundle) return;
    setError(null);
    setFeedbackMessage("");
    try {
      await createFeedback({
        activity_id: bundle.assessment.activity_id,
        assessment_id: bundle.assessment.assessment_id,
        assessment_version: bundle.assessment_version,
        question_id: input.questionId,
        target_type: input.questionId ? "QUESTION" : "ASSESSMENT",
        category: input.category,
        rating: input.rating,
        comment: input.comment,
      });
      setFeedbackMessage("Feedback guardado sin autorizar training ni decisión académica.");
    } catch (caught) {
      setError(caught);
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
      actionHistory={actionHistory}
      actionJobs={actionJobs}
      bundle={bundle}
      busy={busy}
      coverage={coverage}
      downloads={downloads}
      exports={exports}
      feedbackMessage={feedbackMessage}
      onApprove={() => void approve()}
      onExport={(kind) => void exportView(kind)}
      onFeedback={saveReviewFeedback}
      onQuestionAction={actOnQuestion}
      questionBusy={questionBusy}
      onTabChange={setTab}
      onVerify={(questionId, fragmentIndex) => void verify(questionId, fragmentIndex)}
      tab={tab}
      verifying={verifying}
    >
      <div aria-live="polite" ref={actionMessageRef} tabIndex={-1}>{actionMessage}</div>
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
  actionHistory = {},
  actionJobs = {},
  onApprove,
  onExport,
  onFeedback,
  onQuestionAction,
  exports,
  feedbackMessage = "",
  downloads = [],
  coverage = null,
  busy,
  questionBusy = null,
  verifying,
  children,
}: {
  bundle: AssessmentBundle;
  tab: "assessment" | "guide";
  onTabChange: (tab: "assessment" | "guide") => void;
  onVerify: (questionId: string, fragmentIndex: number) => void;
  allEvidenceVerified: boolean;
  actionHistory?: Record<string, QuestionReviewActionRecord[]>;
  actionJobs?: Record<string, JobStatus[]>;
  onApprove: () => void;
  onExport: (kind: ExportKind) => void;
  onFeedback?: (input: {
    questionId?: string;
    category: FeedbackCategory;
    rating: FeedbackRating;
    comment?: string;
  }) => Promise<void>;
  onQuestionAction?: (
    question: SelectedQuestion,
    input: QuestionReviewActionInput,
  ) => Promise<void>;
  exports: ExportRecord[];
  feedbackMessage?: string;
  downloads?: Array<ExportResource | ExportDownloadResource>;
  coverage?: CoverageReport | null;
  busy: boolean;
  questionBusy?: string | null;
  verifying: string | null;
  children?: ReactNode;
}) {
  const { assessment, guide } = bundle;
  const approved = assessment.status === "APPROVED";
  const guideStatus = bundle.guide_status ?? "NOT_AVAILABLE";
  const guideReady = guideStatus === "READY" && guide !== null && guide !== undefined;
  const questions = assessment.questions ?? [];
  const guideItems = guide?.items ?? [];
  const hasUnresolvedQuestionJob = Object.values(actionJobs).some(
    (jobs) => jobs.length > 0,
  );
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

      <LimitedEvidenceWarning />

      <section className="justification-summary" aria-label="Configuración de justificación estudiantil">
        <strong>Justificación estructurada · {assessment.structured_justification.mode.replaceAll("_", " ")}</strong>
        <span>
          {assessment.structured_justification.mode === "ALL"
            ? "Se exige en todas las preguntas."
            : assessment.structured_justification.mode === "SELECTED"
              ? `Se exige en ${(assessment.structured_justification.required_question_ids ?? []).length} preguntas seleccionadas; la evidencia no es total.`
              : "No se exige; la evidencia de justificación no es total."}
        </span>
      </section>

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
              actionRecords={actionHistory[question.question_id] ?? []}
              actionJobs={actionJobs[question.question_id] ?? []}
              actionsBlocked={hasUnresolvedQuestionJob}
              index={index}
              key={question.question_id}
              onVerify={onVerify}
              onQuestionAction={approved ? undefined : onQuestionAction}
              question={question}
              questionBusy={questionBusy === question.question_id}
              questionEvidenceVerified={allEvidenceVerified || question.anchor.fragments.every((fragment, fragmentIndex) => Boolean(receiptFor(receipts, question.question_id, fragmentIndex, fragment.evidence_id)))}
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
        <GuideView
          guide={guide}
          jobId={bundle.guide_job_id}
          questions={questions}
          status={guideStatus}
        />
      </section>

      {!choiceContractsComplete && (
        <div className="error-notice" role="alert">
          Una pregunta CHOICE no contiene alternativas evaluables completas. La aprobación permanece bloqueada.
        </div>
      )}
      {children}

      {coverage && <AssessmentCoverageView report={coverage} />}

      {onFeedback && (
        <ReviewFeedbackForm
          message={feedbackMessage}
          onSubmit={onFeedback}
          questions={questions}
        />
      )}

      <section className="export-panel">
          <div>
            <span className="eyebrow">Vistas derivadas</span>
            <h2>Exportar sin repetir llamadas al modelo</h2>
            <p>Los PDF y el JSON se regeneran desde objetos canónicos ya aprobados.</p>
          </div>
          {approved && guideReady ? <div className="export-actions">
            {([
              ["ASSESSMENT_PDF", "Evaluación PDF"],
              ["ASSESSMENT_HTML", "Evaluación HTML"],
              ["GUIDE_PDF", "Guía PDF"],
              ["GUIDE_HTML", "Guía HTML"],
              ["COVERAGE_CSV", "Cobertura CSV"],
              ["COVERAGE_JSON", "Cobertura JSON"],
              ["CANONICAL_JSON", "JSON canónico"],
            ] as Array<[ExportKind, string]>).map(([kind, label]) => {
              const resource = exports.find((item) => exportKinds(item).includes(kind));
              const download = downloads.find((item) => item.kind === kind);
              const downloadUrl = download?.download_url;
              return downloadUrl ? (
                <a
                  className="button button-secondary"
                  href={downloadUrl}
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
          </div> : approved ? (
            <p>La aprobación ya quedó congelada. Las vistas se habilitan cuando la guía exacta de esta versión esté lista.</p>
          ) : (
            <p>Las nuevas vistas se habilitan cuando la versión queda aprobada y su guía exacta está lista.</p>
          )}
          <ExportHistory exports={exports} />
      </section>

      <footer className="sticky-actions">
        <div>
          <strong>{approved ? "Assessment aprobado" : "Revisión humana obligatoria"}</strong>
          <span>
            {approved
              ? guideReady
                ? "La versión aprobada quedó congelada y su guía exacta está lista."
                : "La versión aprobada quedó congelada; la guía se enriquece aparte y no revoca la aprobación."
              : hasUnresolvedQuestionJob
                ? "Finaliza la regeneración durable y refresca la versión antes de aprobar."
              : allEvidenceVerified
                ? "Todos los fragmentos tienen confirmación durable para tu identidad."
                : "Carga y verifica el localizador exacto de cada fragmento antes de aprobar."}
          </span>
        </div>
        {!approved && (
          <button
            className="button button-primary"
            disabled={!allEvidenceVerified || !choiceContractsComplete || busy || hasUnresolvedQuestionJob}
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
  actionRecords,
  actionJobs,
  actionsBlocked,
  receipts,
  index,
  onVerify,
  onQuestionAction,
  questionBusy,
  questionEvidenceVerified,
  verifying,
}: {
  question: SelectedQuestion;
  review?: QuestionReview;
  evidenceById: Map<string, EvidenceUnit>;
  actionRecords: QuestionReviewActionRecord[];
  actionJobs: JobStatus[];
  actionsBlocked: boolean;
  receipts: EvidenceReceipt[];
  index: number;
  onVerify: (questionId: string, fragmentIndex: number) => void;
  onQuestionAction?: (
    question: SelectedQuestion,
    input: QuestionReviewActionInput,
  ) => Promise<void>;
  questionBusy: boolean;
  questionEvidenceVerified: boolean;
  verifying: string | null;
}) {
  const choices = question.choices ?? [];
  const preliminary = question.preliminary_guide;
  const [action, setAction] = useState<"REJECT" | "EDIT" | "REGENERATE" | null>(null);
  const [reasonCode, setReasonCode] = useState("INSUFFICIENT_GROUNDING");
  const [note, setNote] = useState("");
  const [questionText, setQuestionText] = useState(question.question_text);
  const confirmationLabel = action === "EDIT"
    ? "Confirmar edición"
    : action === "REJECT"
      ? "Confirmar rechazo"
      : "Confirmar regeneración";

  useEffect(() => {
    setQuestionText(question.question_text);
  }, [question.question_text]);

  const submitAction = async (event: FormEvent) => {
    event.preventDefault();
    if (!action || !onQuestionAction) return;
    const input: QuestionReviewActionInput = {
      action,
      note: note.trim() || undefined,
      ...(action === "REJECT" || action === "REGENERATE"
        ? { reason_code: reasonCode }
        : {}),
      ...(action === "EDIT"
        ? { replacement: { ...structuredClone(question), question_text: questionText.trim() } }
        : {}),
    };
    await onQuestionAction(question, input);
    setAction(null);
    setNote("");
  };
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
          <span className="mini-label">
            {review
              ? "Review histórico P08 · compatibilidad no autoritativa"
              : "Validación determinista activa"}
          </span>
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
              <ReferenceList label="Evidencia del review histórico" values={review.evidence_ids ?? []} />
              <ReferenceList label="Fuentes de curso" values={review.source_ids ?? []} emptyLabel="Sin fuentes de curso: contexto CLOSED." />
            </>
          ) : (
            <p className="muted">
              La pregunta P07 superó las invariantes deterministas activas. El runtime actual no ejecuta P08.
            </p>
          )}
          <Diagnostics items={review?.diagnostics} />
          {(review?.critical_failure_codes ?? []).length > 0 && (
            <div className="critical-codes">
              {(review?.critical_failure_codes ?? []).map((code) => <code key={code}>{code}</code>)}
            </div>
          )}
        </section>
      </div>

      {onQuestionAction && (
        <section className="question-review-actions" aria-label={`Acciones para ${question.question_id}`}>
          {actionJobs.length > 0 && (
            <div aria-live="polite" className="question-action-pending">
              <h3>Regeneración durable pendiente</h3>
              <p>
                La pregunta original permanece vigente. Autoriza y ejecuta el job <code>QUESTION_ACTION</code> exacto fuera del web runtime; luego refresca esta página.
              </p>
              {actionJobs.map((job) => (
                <JobControlPanel jobId={job.job_id} key={job.job_id} />
              ))}
            </div>
          )}
          {!questionEvidenceVerified && <p className="muted">Verifica primero cada fragmento de esta pregunta para habilitar las acciones.</p>}
          <div className="question-action-buttons">
            <button className="button button-secondary" disabled={questionBusy || !questionEvidenceVerified || actionsBlocked} onClick={() => void onQuestionAction(question, { action: "ACCEPT" })} type="button">Aceptar pregunta</button>
            <button aria-expanded={action === "EDIT"} className="button button-secondary" disabled={questionBusy || !questionEvidenceVerified || actionsBlocked} onClick={() => setAction(action === "EDIT" ? null : "EDIT")} type="button">Editar pregunta</button>
            <button aria-expanded={action === "REJECT"} className="button button-secondary" disabled={questionBusy || !questionEvidenceVerified || actionsBlocked} onClick={() => setAction(action === "REJECT" ? null : "REJECT")} type="button">Rechazar pregunta</button>
            <button aria-expanded={action === "REGENERATE"} className="button button-secondary" disabled={questionBusy || !questionEvidenceVerified || actionsBlocked} onClick={() => setAction(action === "REGENERATE" ? null : "REGENERATE")} type="button">Regenerar pregunta</button>
          </div>
          {action && (
            <form className="question-action-form" onSubmit={(event) => void submitAction(event)}>
              <h3>{action === "EDIT" ? "Editar copia completa" : action === "REJECT" ? "Confirmar rechazo" : "Regeneración localizada"}</h3>
              {action === "EDIT" ? (
                <label className="field"><span>Texto de la pregunta</span><textarea autoFocus maxLength={4000} onChange={(event) => setQuestionText(event.target.value)} required rows={4} value={questionText} /></label>
              ) : (
                <label className="field"><span>Motivo</span><select autoFocus onChange={(event) => setReasonCode(event.target.value)} required value={reasonCode}><option value="INSUFFICIENT_GROUNDING">Grounding insuficiente</option><option value="NOT_ANSWERABLE">No respondible</option><option value="DUPLICATE_OPPORTUNITY">Oportunidad duplicada</option><option value="TEACHER_JUDGMENT">Juicio docente</option></select></label>
              )}
              <label className="field"><span>Nota opcional</span><textarea maxLength={2000} onChange={(event) => setNote(event.target.value)} rows={2} value={note} /></label>
              <div className="form-actions"><button className="button button-primary" disabled={questionBusy || (action === "EDIT" && !questionText.trim())} type="submit">{questionBusy ? "Aplicando…" : confirmationLabel}</button><button className="button button-quiet" disabled={questionBusy} onClick={() => setAction(null)} type="button">Cancelar</button></div>
            </form>
          )}
        </section>
      )}

      {actionRecords.length > 0 && (
        <details className="question-action-history">
          <summary>Historial durable de acciones ({actionRecords.length})</summary>
          <ol>
            {actionRecords.map((record) => (
              <li key={record.record_id}>
                <header><strong>{record.action.action}</strong><StatusBadge status={record.status} /></header>
                <p>Versión {record.assessment_version_before} → {record.assessment_version_after ?? "sin cambio"} · revalidación {record.revalidation_status}</p>
                <small>{new Date(record.recorded_at).toLocaleString("es-CL")} · {record.action.reason_code ?? "sin reason code"}</small>
                {record.after_question && record.after_question.question_text !== record.before_question.question_text && (
                  <details><summary>Ver before / after</summary><p><strong>Before:</strong> {record.before_question.question_text}</p><p><strong>After:</strong> {record.after_question.question_text}</p></details>
                )}
                <Diagnostics items={record.diagnostics} />
              </li>
            ))}
          </ol>
        </details>
      )}

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

function ReviewFeedbackForm({
  questions,
  message,
  onSubmit,
}: {
  questions: SelectedQuestion[];
  message: string;
  onSubmit: (input: {
    questionId?: string;
    category: FeedbackCategory;
    rating: FeedbackRating;
    comment?: string;
  }) => Promise<void>;
}) {
  const [target, setTarget] = useState("ASSESSMENT");
  const [category, setCategory] = useState<FeedbackCategory>("QUESTION_QUALITY");
  const [rating, setRating] = useState<FeedbackRating>("NEUTRAL");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit({
        questionId: target === "ASSESSMENT" ? undefined : target,
        category,
        rating,
        comment: comment.trim() || undefined,
      });
      setComment("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="feedback-card review-feedback-card" onSubmit={(event) => void submit(event)}>
      <span className="eyebrow">Feedback de revisión</span>
      <h2>Registrar feedback estructurado</h2>
      <p>Queda asociado a esta versión; no se convierte en training data ni en una decisión académica.</p>
      <div className="review-feedback-fields">
        <label className="field"><span>Objeto del feedback</span><select onChange={(event) => setTarget(event.target.value)} value={target}><option value="ASSESSMENT">Assessment completo</option>{questions.map((question, index) => <option key={question.question_id} value={question.question_id}>Pregunta {index + 1}</option>)}</select></label>
        <label className="field"><span>Categoría de feedback</span><select onChange={(event) => setCategory(event.target.value as FeedbackCategory)} value={category}><option value="GROUNDING">Grounding</option><option value="ANSWERABILITY">Respondibilidad</option><option value="QUESTION_QUALITY">Calidad de pregunta</option><option value="GUIDE_QUALITY">Calidad de guía</option><option value="COVERAGE">Cobertura</option><option value="WORKFLOW">Flujo</option><option value="EXPORT">Exportación</option><option value="OTHER">Otro</option></select></label>
        <label className="field"><span>Valoración del feedback</span><select onChange={(event) => setRating(event.target.value as FeedbackRating)} value={rating}><option value="VERY_UNHELPFUL">Muy poco útil</option><option value="UNHELPFUL">Poco útil</option><option value="NEUTRAL">Neutral</option><option value="HELPFUL">Útil</option><option value="VERY_HELPFUL">Muy útil</option></select></label>
      </div>
      <label className="field"><span>Comentario opcional de revisión</span><textarea maxLength={2000} onChange={(event) => setComment(event.target.value)} rows={3} value={comment} /></label>
      <div className="form-actions"><button className="button button-primary" disabled={busy} type="submit">{busy ? "Guardando…" : "Guardar feedback de revisión"}</button></div>
      <p aria-live="polite">{message}</p>
    </form>
  );
}

function exportKinds(item: ExportRecord): ExportKind[] {
  return item.requested_kinds;
}

function ExportHistory({ exports }: { exports: ExportRecord[] }) {
  if (!exports.length) return <p className="muted">Aún no hay exportaciones persistidas.</p>;
  return (
    <div className="table-scroll" tabIndex={0} aria-label="Historial desplazable de exportaciones">
      <table className="batch-table export-history">
        <caption>Historial de exportaciones derivadas</caption>
        <thead><tr><th scope="col">Export ID</th><th scope="col">Vistas</th><th scope="col">Estado</th><th scope="col">Artefactos</th><th scope="col">Modelo</th></tr></thead>
        <tbody>{exports.map((item) => (
          <tr key={item.export_id}>
            <th scope="row"><code>{item.export_id}</code></th>
            <td>{exportKinds(item).map((kind) => humanizeExport(kind)).join(", ")}</td>
            <td><StatusBadge status={item.status} /></td>
            <td>{(item.artifacts ?? []).length}</td>
            <td>{item.model_call_delta} llamadas</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function humanizeExport(value: ExportKind): string {
  return value.replaceAll("_", " ").toLocaleLowerCase("es-CL");
}

function AssessmentCoverageView({ report }: { report: CoverageReport }) {
  return (
    <section className="coverage-review-panel" aria-labelledby="assessment-coverage-title">
      <span className="eyebrow">Trazabilidad de la versión</span>
      <h2 id="assessment-coverage-title">Cobertura del submission</h2>
      <p>{(report.traces ?? []).length} oportunidades trazadas contra el snapshot sellado.</p>
      <div className="metric-grid">
        {report.summary.map((item) => (
          <article className="metric-card" key={item.dimension_id}>
            <span>{item.dimension_id}</span>
            <strong>{item.selected_opportunity_count}/{item.available_opportunity_count}</strong>
            <small>{item.evidence_unit_count} unidades de evidencia</small>
          </article>
        ))}
      </div>
    </section>
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
  status,
  jobId,
  questions,
}: {
  guide?: EvaluationGuide | null;
  status: string;
  jobId?: string | null;
  questions: SelectedQuestion[];
}) {
  if (status === "NOT_AVAILABLE") {
    return (
      <div className="processing-card" role="status">
        <h2>Guía posterior a la aprobación</h2>
        <p>P09 se ejecutará una sola vez sobre la versión que apruebes. La revisión y la aprobación no dependen de una guía previa.</p>
      </div>
    );
  }
  if (status === "PENDING" || status === "BUILDING") {
    return (
      <div className="processing-card" role="status">
        <span className="spinner" aria-hidden="true" />
        <h2>{status === "PENDING" ? "Guía pendiente" : "Construyendo guía"}</h2>
        <p>La aprobación ya es durable. P09 está enriqueciendo únicamente la guía de esta versión.</p>
        {jobId ? <code>{jobId}</code> : null}
      </div>
    );
  }
  if (status === "FAILED" || status === "NEEDS_REVIEW" || !guide) {
    return (
      <div className="error-notice" role="status">
        <h2>La guía no quedó lista</h2>
        <p>La evaluación sigue aprobada. No se publicó una guía parcial; puedes revisar o reintentar el job técnico.</p>
        {guide ? <Diagnostics items={guide.diagnostics} /> : null}
      </div>
    );
  }
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
              <ReferenceList label="Condiciones de aceptación" values={item.guide.acceptance_conditions ?? []} />
              <ReferenceList label="Alternativas aceptables" values={item.guide.acceptable_alternatives ?? []} />
              <ReferenceList label="Posibles errores conceptuales a observar" values={item.guide.misconceptions ?? []} />
              <ReferenceList label="No permite inferir" values={item.guide.cannot_infer ?? []} />
              <ReferenceList label="Incertidumbres semánticas" values={item.guide.semantic_uncertainties ?? []} />
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
