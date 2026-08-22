import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route } from "wouter";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  bulkApproveAssessments,
  createFeedback,
  createSubmissionBatch,
  getActivityCoverage,
  getActivityMetrics,
  getJobControl,
  listActivityFeedback,
  listActivitySubmissions,
  listBulkApprovalHistory,
  uploadSubmissionArtifact,
} from "../api/client";
import type {
  BulkApprovalRecord,
  CoverageReport,
  ExperimentMetrics,
  FeedbackEvent,
  JobControlView,
  JobStatus,
  Stage2Submission,
} from "../api/types";
import { MemoryRouter } from "../routing";
import { assessmentBundle, submission } from "../test/fixtures";
import { ActivityLabPage } from "./ActivityLabPage";
import { AssessmentReview } from "./AssessmentReviewPage";

vi.mock("../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/client")>();
  return {
    ...original,
    bulkApproveAssessments: vi.fn(),
    createFeedback: vi.fn(),
    createSubmissionBatch: vi.fn(),
    getActivityCoverage: vi.fn(),
    getActivityMetrics: vi.fn(),
    getJobControl: vi.fn(),
    listActivityFeedback: vi.fn(),
    listActivitySubmissions: vi.fn(),
    listBulkApprovalHistory: vi.fn(),
    uploadSubmissionArtifact: vi.fn(),
  };
});

const HASH = `sha256:${"a".repeat(64)}`;

const coverage: CoverageReport = {
  schema_version: "1.2.0",
  report_id: "coverage_01",
  tenant_id: "tenant_01",
  activity_id: "activity_01",
  scope: "ACTIVITY",
  blueprint_id: "blueprint_01",
  blueprint_version: 3,
  source_snapshot_hash: HASH,
  summary: [{
    dimension_id: "dim_causal",
    available_variant_count: 2,
    available_opportunity_count: 3,
    selected_opportunity_count: 2,
    reused_variant_count: 0,
    evidence_unit_count: 2,
    diagnostics: [],
  }],
  traces: [{
    submission_id: "submission_01",
    assessment_id: "assessment_01",
    assessment_version: 1,
    dimension_id: "dim_causal",
    criterion_ids: ["criterion_01"],
    variant_id: "variant_tradeoff",
    opportunity_id: "opportunity_01",
    evidence_ids: ["evidence_01"],
    cognitive_operation: "EXPLAIN_MECHANISM",
    planning_role: "PRIMARY",
    outcome: "REVIEWED",
    reused_variant: false,
    diagnostics: [],
  }],
  diagnostics: [],
  generated_at: "2026-08-07T12:10:00Z",
};

const metrics: ExperimentMetrics = {
  schema_version: "1.2.0",
  metrics_id: "metrics_01",
  tenant_id: "tenant_01",
  activity_id: "activity_01",
  technical: { job_count: 2, succeeded_count: 1, failed_count: 1, cancelled_count: 0, retry_count: 1, latency_p50_ms: 1200, latency_p95_ms: 2400, input_tokens: 100, cached_input_tokens: 20, output_tokens: 40, estimated_cost_usd: 0.1, actual_cost_usd: 0.08 },
  quality: { assessment_count: 1, fail_closed_count: 0, defect_count: 1, exact_plan_count: 1, replacement_count: 0 },
  human_review: { reviewed_question_count: 1, accepted_count: 1, edited_count: 0, rejected_count: 0, regenerated_count: 0, review_seconds: 35 },
  by_stage: [],
  by_model: [],
  window_start: "2026-08-07T12:00:00Z",
  window_end: "2026-08-07T12:09:00Z",
  generated_at: "2026-08-07T12:10:00Z",
};

const feedback: FeedbackEvent = {
  schema_version: "1.2.0",
  feedback_id: "feedback_01",
  tenant_id: "tenant_01",
  activity_id: "activity_01",
  target_type: "ACTIVITY",
  actor_id: "teacher_01",
  category: "WORKFLOW",
  rating: "HELPFUL",
  comment: "El filtro fue claro.",
  training_use_allowed: false,
  public_dataset_use_allowed: false,
  academic_decision_use_allowed: false,
  created_at: "2026-08-07T12:10:00Z",
};

const batchRecord: BulkApprovalRecord = {
  schema_version: "1.1.0",
  approval_id: "approval_01",
  request_id: "request_01",
  tenant_id: "tenant_01",
  actor_id: "teacher_01",
  scope: "SELECTED_ELIGIBLE_ASSESSMENTS",
  approved_at: "2026-08-07T12:11:00Z",
  requested_targets: [{ assessment_id: "assessment_01", assessment_version: 1 }],
  approved_targets: [{ assessment_id: "assessment_01", assessment_version: 1 }],
  excluded_targets: [],
};

const uploaded: Stage2Submission = {
  ...submission,
  submission_id: "submission_upload",
  subject_ref: "estudiante_015",
  status: "UPLOADED",
  current_stage: null,
  progress: 0,
  active_job_id: null,
  artifact_uploaded: false,
  assessment_id: null,
};

const reviewable: Stage2Submission = {
  ...submission,
  artifact_uploaded: true,
  assessment_version: 1,
};

const queuedQuestionActionJob: JobStatus = {
  schema_version: "1.1.0",
  job_id: "job_question_action_01",
  tenant_id: "tenant_01",
  aggregate_id: "submission_01",
  stage: "QUESTION_GENERATE",
  status: "QUEUED",
  progress: 0,
  attempt: 0,
  diagnostics: [],
};

const queuedQuestionActionControl: JobControlView = {
  job: queuedQuestionActionJob,
  stage_runs: [],
  control_records: [],
  allowed_actions: ["CANCEL"],
  control_state: "ACTIVE",
};

describe("Stage 2 activity lab", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(listActivitySubmissions).mockResolvedValue([uploaded, reviewable]);
    vi.mocked(getActivityCoverage).mockResolvedValue(coverage);
    vi.mocked(getActivityMetrics).mockResolvedValue(metrics);
    vi.mocked(listActivityFeedback).mockResolvedValue([feedback]);
    vi.mocked(listBulkApprovalHistory).mockResolvedValue([]);
    vi.mocked(createSubmissionBatch).mockResolvedValue({ submissions: [], created_count: 0 });
    vi.mocked(bulkApproveAssessments).mockResolvedValue(batchRecord);
    vi.mocked(createFeedback).mockResolvedValue({ ...feedback, feedback_id: "feedback_02" });
    vi.mocked(uploadSubmissionArtifact).mockResolvedValue({} as never);
  });

  it("creates a pseudonymous batch, accepts DOCX, filters independent states and requires bulk confirmation", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/activities/activity_01/lab"]}>
        <Route path="/activities/:activityId/lab"><ActivityLabPage /></Route>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Estados por entrega" })).toBeInTheDocument();
    expect(screen.getByText(/no detecta IA/i)).toHaveTextContent(/la decisión académica sigue siendo humana/i);
    const upload = screen.getByLabelText("Elegir archivo para estudiante_015");
    expect(upload).toHaveAttribute("accept", expect.stringContaining(".docx"));

    await user.type(screen.getByLabelText(/Referencias seudónimas/), "estudiante_020\nestudiante_021\nestudiante_020");
    expect(screen.getByText("2 referencias únicas listas.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Crear entregas del lote" }));
    expect(createSubmissionBatch).toHaveBeenCalledWith("activity_01", ["estudiante_020", "estudiante_021"]);

    await user.selectOptions(screen.getByLabelText("Filtrar por estado"), "NEEDS_REVIEW");
    expect(screen.getByText("estudiante_014")).toBeInTheDocument();
    expect(screen.queryByText("estudiante_015")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Seleccionar assessment de estudiante_014"));
    const bulkButton = screen.getByRole("button", { name: "Aprobar selección confirmada" });
    expect(bulkButton).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /Confirmo la aprobación/ }));
    expect(bulkButton).toBeEnabled();
    await user.click(bulkButton);
    expect(bulkApproveAssessments).toHaveBeenCalledWith("activity_01", [{ assessment_id: "assessment_01", assessment_version: 1 }]);
    expect(await screen.findByRole("heading", { name: "Aprobados (1)" })).toBeInTheDocument();
  });

  it("replaces the file chooser with a persisted marker after a successful upload", async () => {
    const user = userEvent.setup();
    vi.mocked(listActivitySubmissions)
      .mockReset()
      .mockResolvedValueOnce([uploaded])
      .mockResolvedValue([{ ...uploaded, artifact_uploaded: true }]);
    render(
      <MemoryRouter initialEntries={["/activities/activity_01/lab"]}>
        <Route path="/activities/:activityId/lab"><ActivityLabPage /></Route>
      </MemoryRouter>,
    );

    const chooser = await screen.findByLabelText(
      "Elegir archivo para estudiante_015",
    );
    await user.upload(
      chooser,
      new File(["synthetic evidence"], "submission.md", {
        type: "text/markdown",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Cargar" }));

    await waitFor(() =>
      expect(uploadSubmissionArtifact).toHaveBeenCalledOnce(),
    );
    expect(await screen.findByText("Archivo persistido")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Elegir archivo para estudiante_015"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cargar" })).not.toBeInTheDocument();
  });

  it("supports roving tabs with arrows, Home and End and submits canonical feedback enums", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/activities/activity_01/lab"]}>
        <Route path="/activities/:activityId/lab"><ActivityLabPage /></Route>
      </MemoryRouter>,
    );
    const submissionsTab = await screen.findByRole("tab", { name: /Entregas/ });
    submissionsTab.focus();
    await user.keyboard("{End}");
    const feedbackTab = screen.getByRole("tab", { name: /Feedback/ });
    expect(feedbackTab).toHaveFocus();
    expect(feedbackTab).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}");
    expect(submissionsTab).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(feedbackTab).toHaveFocus();

    await user.click(screen.getByLabelText("Muy útil"));
    await user.selectOptions(screen.getByLabelText("Categoría"), "QUESTION_QUALITY");
    await user.type(screen.getByLabelText("Comentario opcional"), "Buena separación de estados.");
    await user.click(screen.getByRole("button", { name: "Guardar feedback" }));
    await waitFor(() => expect(createFeedback).toHaveBeenCalledWith({
      activity_id: "activity_01",
      target_type: "ACTIVITY",
      category: "QUESTION_QUALITY",
      rating: "VERY_HELPFUL",
      comment: "Buena separación de estados.",
    }));
  });
});

describe("Stage 2 question actions", () => {
  beforeEach(() => {
    vi.mocked(getJobControl).mockResolvedValue(queuedQuestionActionControl);
  });

  it("edits only question_text over a complete canonical copy", async () => {
    const user = userEvent.setup();
    const onQuestionAction = vi.fn().mockResolvedValue(undefined);
    render(
      <AssessmentReview
        allEvidenceVerified
        bundle={structuredClone(assessmentBundle)}
        busy={false}
        exports={[]}
        onApprove={vi.fn()}
        onExport={vi.fn()}
        onQuestionAction={onQuestionAction}
        onTabChange={vi.fn()}
        onVerify={vi.fn()}
        tab="assessment"
        verifying={null}
      />,
    );

    expect(screen.getByText(/no prueba autoría, no prueba fraude/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Editar pregunta" }));
    const editor = screen.getByRole("textbox", { name: "Texto de la pregunta" });
    await user.clear(editor);
    await user.type(editor, "¿Qué evidencia respalda la decisión principal?");
    await user.click(screen.getByRole("button", { name: "Confirmar edición" }));

    await waitFor(() => expect(onQuestionAction).toHaveBeenCalledTimes(1));
    const original = assessmentBundle.assessment.questions?.[0];
    if (!original) throw new Error("fixture question missing");
    expect(onQuestionAction).toHaveBeenCalledWith(
      expect.objectContaining({ question_id: original.question_id }),
      {
        action: "EDIT",
        note: undefined,
        replacement: { ...original, question_text: "¿Qué evidencia respalda la decisión principal?" },
      },
    );
    const call = onQuestionAction.mock.calls[0][1];
    expect(call.replacement.question_id).toBe(original.question_id);
    expect(call.replacement.anchor).toEqual(original.anchor);
  });

  it("requires reason codes for reject and localized regeneration", async () => {
    const user = userEvent.setup();
    const onQuestionAction = vi.fn().mockResolvedValue(undefined);
    render(
      <AssessmentReview
        allEvidenceVerified
        bundle={structuredClone(assessmentBundle)}
        busy={false}
        exports={[]}
        onApprove={vi.fn()}
        onExport={vi.fn()}
        onQuestionAction={onQuestionAction}
        onTabChange={vi.fn()}
        onVerify={vi.fn()}
        tab="assessment"
        verifying={null}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Regenerar pregunta" }));
    const form = screen.getByRole("heading", { name: "Regeneración localizada" }).closest("form");
    if (!form) throw new Error("action form missing");
    await user.selectOptions(within(form).getByLabelText("Motivo"), "NOT_ANSWERABLE");
    await user.click(within(form).getByRole("button", { name: "Confirmar regeneración" }));
    expect(onQuestionAction).toHaveBeenCalledWith(
      expect.objectContaining({ question_id: "question_01" }),
      { action: "REGENERATE", reason_code: "NOT_ANSWERABLE", note: undefined },
    );
  });

  it("keeps the original question visible and blocks review while a durable regeneration job is pending", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const originalQuestion = assessmentBundle.assessment.questions?.[0];
    if (!originalQuestion) throw new Error("fixture question missing");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });

    const { rerender } = render(
      <AssessmentReview
        actionJobs={{ [originalQuestion.question_id]: [queuedQuestionActionJob] }}
        allEvidenceVerified
        bundle={structuredClone(assessmentBundle)}
        busy={false}
        exports={[]}
        onApprove={onApprove}
        onExport={vi.fn()}
        onQuestionAction={vi.fn()}
        onTabChange={vi.fn()}
        onVerify={vi.fn()}
        tab="assessment"
        verifying={null}
      />,
    );

    expect(screen.getByRole("heading", { name: originalQuestion.question_text })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Regeneración durable pendiente" })).toBeInTheDocument();
    expect(screen.getByText(/La pregunta original permanece vigente/)).toBeInTheDocument();
    expect(screen.getByText("QUESTION_ACTION")).toBeInTheDocument();
    expect(await screen.findByText("job_question_action_01")).toBeInTheDocument();
    expect(screen.getByText("En cola")).toBeInTheDocument();

    for (const label of [
      "Aceptar pregunta",
      "Editar pregunta",
      "Rechazar pregunta",
      "Regenerar pregunta",
      "Aprobar Assessment",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }

    await user.click(screen.getByRole("button", { name: "Copiar job ID" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("job_question_action_01");
    expect(onApprove).not.toHaveBeenCalled();

    const refreshedBundle = structuredClone(assessmentBundle);
    refreshedBundle.assessment_version = 2;
    refreshedBundle.etag = `sha256:${"b".repeat(64)}`;
    const refreshedQuestion = refreshedBundle.assessment.questions?.[0];
    if (!refreshedQuestion) throw new Error("refreshed fixture question missing");
    refreshedQuestion.question_text = "¿Qué mecanismo alternativo explica la evidencia sellada?";
    rerender(
      <AssessmentReview
        actionJobs={{}}
        allEvidenceVerified
        bundle={refreshedBundle}
        busy={false}
        exports={[]}
        onApprove={onApprove}
        onExport={vi.fn()}
        onQuestionAction={vi.fn()}
        onTabChange={vi.fn()}
        onVerify={vi.fn()}
        tab="assessment"
        verifying={null}
      />,
    );

    expect(screen.queryByText("Regeneración durable pendiente")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: originalQuestion.question_text })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: refreshedQuestion.question_text })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aprobar Assessment" })).toBeEnabled();
  });

  it("associates governed feedback with an exact assessment question", async () => {
    const user = userEvent.setup();
    const onFeedback = vi.fn().mockResolvedValue(undefined);
    render(
      <AssessmentReview
        allEvidenceVerified
        bundle={structuredClone(assessmentBundle)}
        busy={false}
        exports={[]}
        onApprove={vi.fn()}
        onExport={vi.fn()}
        onFeedback={onFeedback}
        onTabChange={vi.fn()}
        onVerify={vi.fn()}
        tab="assessment"
        verifying={null}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Objeto del feedback"), "question_01");
    await user.selectOptions(screen.getByLabelText("Categoría de feedback"), "GROUNDING");
    await user.selectOptions(screen.getByLabelText("Valoración del feedback"), "HELPFUL");
    await user.type(screen.getByLabelText("Comentario opcional de revisión"), "La evidencia fue fácil de localizar.");
    await user.click(screen.getByRole("button", { name: "Guardar feedback de revisión" }));

    expect(onFeedback).toHaveBeenCalledWith({
      questionId: "question_01",
      category: "GROUNDING",
      rating: "HELPFUL",
      comment: "La evidencia fue fácil de localizar.",
    });
  });
});
