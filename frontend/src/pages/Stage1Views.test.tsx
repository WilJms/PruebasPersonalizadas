import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route } from "wouter";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  approveBlueprint,
  createPolicyDecision,
  generateBlueprint,
  getActivity,
  getActivityAmbiguity,
  getJob,
  getJobControl,
  getLatestBlueprint,
  listActivities,
  updateBlueprint,
} from "../api/client";
import type { ActivityResource, AssessmentBundle } from "../api/types";
import {
  ambiguityView,
  assessmentBundle,
  blueprintView,
  failedTechnicalJob,
  submission,
} from "../test/fixtures";
import { ActivityCreatePage } from "./ActivityCreatePage";
import { ActivitiesPage } from "./ActivitiesPage";
import { AssessmentReview } from "./AssessmentReviewPage";
import { BlueprintPage } from "./BlueprintPage";
import { SubmissionProgress } from "./SubmissionPage";
import { MemoryRouter } from "../routing";

vi.mock("../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/client")>();
  return {
    ...original,
    approveBlueprint: vi.fn(),
    createPolicyDecision: vi.fn(),
    generateBlueprint: vi.fn(),
    getActivity: vi.fn(),
    getActivityAmbiguity: vi.fn(),
    getJob: vi.fn(),
    getJobControl: vi.fn(),
    getLatestBlueprint: vi.fn(),
    listActivities: vi.fn(),
    updateBlueprint: vi.fn(),
  };
});

function activityResource(
  overrides: Partial<ActivityResource> & Pick<ActivityResource, "activity_id" | "title">,
): ActivityResource {
  const { activity_id, title, ...rest } = overrides;
  return {
    schema_version: "1.1.0",
    activity_id,
    tenant_id: "tenant_01",
    title,
    output_language: "es-CL",
    assessment_modality: "WRITTEN",
    question_count: 1,
    target_total_minutes: 8,
    allowed_response_formats: ["OPEN_SHORT"],
    allowed_artifact_media_types: ["text/plain"],
    structured_justification_mode: "NOT_REQUIRED",
    context_mode: "CLOSED",
    course_source_ids: [],
    priority_criterion_ids: [],
    require_blueprint_approval: true,
    status: "DRAFT",
    created_at: "2026-07-31T12:00:00Z",
    updated_at: "2026-07-31T12:00:00Z",
    journey: {
      continue_path: `/activities/${activity_id}/edit`,
      next_action: "EDIT_ACTIVITY",
      blueprint: null,
      submission: null,
      job: null,
      assessment: null,
    },
    ...rest,
  };
}

describe("Stage 1 activity configuration", () => {
  it("captures the allowed controls and does not expose depth or cognitive operations", () => {
    const { container } = render(
      <MemoryRouter>
        <ActivityCreatePage />
      </MemoryRouter>,
    );

    for (const name of [
      "title",
      "output_language",
      "assessment_modality",
      "question_count",
      "target_total_minutes",
      "allowed_response_formats",
      "allowed_artifact_media_types",
      "structured_justification_mode",
    ]) {
      expect(container.querySelector(`[name="${name}"]`)).toBeInTheDocument();
    }

    expect(container.querySelector('[name="depth"]')).not.toBeInTheDocument();
    expect(container.querySelector('[name="cognitive_operations"]')).not.toBeInTheDocument();
    expect(screen.getByText("Anotación o diagrama")).toBeInTheDocument();

    const assignment = container.querySelector<HTMLInputElement>('[name="assignment_prompt"]');
    const rubric = container.querySelector<HTMLInputElement>('[name="rubric"]');
    expect(assignment).toBeRequired();
    expect(rubric).not.toBeRequired();
    expect(assignment?.accept.toLowerCase()).not.toContain("docx");
    expect(rubric?.accept.toLowerCase()).not.toContain("docx");
  });
});

describe("Stage 1 durable landing", () => {
  it("recovers server-confirmed draft, pipeline, submission and assessment states", async () => {
    vi.mocked(listActivities).mockResolvedValue([
      activityResource({ activity_id: "activity_draft", title: "Borrador durable" }),
      activityResource({
        activity_id: "activity_running",
        title: "Blueprint en curso",
        status: "QUEUED",
        journey: {
          continue_path: "/activities/activity_running/blueprint",
          next_action: "VIEW_PROGRESS",
          blueprint: null,
          submission: null,
          job: {
            job_id: "job_running",
            stage: "BLUEPRINT_BUILD",
            status: "RUNNING",
            progress: 0.5,
          },
          assessment: null,
        },
      }),
      activityResource({
        activity_id: "activity_uploaded",
        title: "Entrega lista para iniciar",
        status: "BLUEPRINT_APPROVED",
        journey: {
          continue_path: "/submissions/submission_uploaded",
          next_action: "RUN_SUBMISSION",
          blueprint: { version: 2, status: "APPROVED", etag: '"blueprint-2"' },
          submission: {
            submission_id: "submission_uploaded",
            status: "UPLOADED",
            active_job_id: null,
          },
          job: null,
          assessment: null,
        },
      }),
      activityResource({
        activity_id: "activity_review",
        title: "Assessment por revisar",
        status: "BLUEPRINT_APPROVED",
        journey: {
          continue_path: "/submissions/submission_review/review",
          next_action: "REVIEW_ASSESSMENT",
          blueprint: { version: 3, status: "APPROVED", etag: '"blueprint-3"' },
          submission: {
            submission_id: "submission_review",
            status: "NEEDS_REVIEW",
            active_job_id: "job_done",
          },
          job: {
            job_id: "job_done",
            stage: "FINALIZE",
            status: "SUCCEEDED",
            progress: 1,
          },
          assessment: {
            assessment_id: "assessment_01",
            version: 1,
            status: "NEEDS_REVIEW",
            etag: '"assessment-1"',
          },
        },
      }),
    ]);

    render(
      <MemoryRouter initialEntries={["/activities"]}>
        <Route path="/activities"><ActivitiesPage /></Route>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Borrador durable" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Blueprint en curso" })).toBeInTheDocument();
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Estimar e iniciar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revisar Assessment" })).toBeInTheDocument();
    expect(listActivities).toHaveBeenCalledTimes(1);
  });
});

describe("Stage 1 blueprint review", () => {
  beforeEach(() => {
    vi.mocked(getLatestBlueprint).mockReset().mockResolvedValue(structuredClone(blueprintView));
    vi.mocked(getJob).mockReset();
    vi.mocked(getJobControl).mockReset().mockResolvedValue({
      job: failedTechnicalJob,
      stage_runs: [],
      control_records: [],
      allowed_actions: [],
      control_state: "ACTIVE",
      failure_class: "PERMANENT",
    });
    vi.mocked(getActivity).mockReset();
    vi.mocked(getActivityAmbiguity).mockReset();
    vi.mocked(createPolicyDecision).mockReset();
    vi.mocked(generateBlueprint).mockReset();
    vi.mocked(updateBlueprint).mockReset();
    vi.mocked(approveBlueprint).mockReset();
  });

  it("shows dimensions, variants, supported operations, opportunities, version and ETag", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/activities/activity_01/blueprint"]}>
        <Route path="/activities/:activityId/blueprint"><BlueprintPage /></Route>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Comprensión causal" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Decisión con trade-off" })).toBeInTheDocument();
    expect(screen.getAllByText("EXPLAIN MECHANISM").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Efecto de la decisión principal")).toBeInTheDocument();
    expect(screen.getByText(/blueprint-3/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Editar blueprint" }));
    expect(screen.getByRole("textbox", { name: "Nombre de dimensión 1" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Foco opportunity_template_01" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /operación/i })).not.toBeInTheDocument();
  });

  it("waits for the durable P05 job before presenting the edited blueprint version", async () => {
    const user = userEvent.setup();
    const reviewed = structuredClone(blueprintView);
    reviewed.etag = '"sha256:blueprint-4"';
    reviewed.version = 4;
    reviewed.blueprint.blueprint_version = 4;
    reviewed.blueprint.dimensions[0].name = "Comprensión causal revisada";
    vi.mocked(getLatestBlueprint)
      .mockReset()
      .mockResolvedValueOnce(structuredClone(blueprintView))
      .mockResolvedValueOnce(reviewed);
    vi.mocked(updateBlueprint).mockResolvedValue({
      ...failedTechnicalJob,
      job_id: "job_blueprint_review",
      aggregate_id: "activity_01",
      stage: "BLUEPRINT_REVIEW",
      status: "QUEUED",
      progress: 0,
      attempt: 1,
      diagnostics: [],
    });
    vi.mocked(getJob).mockResolvedValue({
      ...failedTechnicalJob,
      job_id: "job_blueprint_review",
      aggregate_id: "activity_01",
      stage: "BLUEPRINT_REVIEW",
      status: "SUCCEEDED",
      progress: 1,
      attempt: 1,
      diagnostics: [],
    });

    render(
      <MemoryRouter initialEntries={["/activities/activity_01/blueprint"]}>
        <Route path="/activities/:activityId/blueprint"><BlueprintPage /></Route>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Editar blueprint" }));
    const name = screen.getByRole("textbox", { name: "Nombre de dimensión 1" });
    await user.clear(name);
    await user.type(name, "Comprensión causal revisada");
    await user.click(screen.getByRole("button", { name: "Guardar nueva versión" }));

    await waitFor(() =>
      expect(updateBlueprint).toHaveBeenCalledWith(
        "activity_01",
        expect.objectContaining({
          blueprint_version: 3,
          dimensions: expect.arrayContaining([
            expect.objectContaining({ name: "Comprensión causal revisada" }),
          ]),
        }),
        blueprintView.etag,
      ),
    );
    expect(await screen.findByRole("heading", { name: "Comprensión causal revisada" })).toBeInTheDocument();
    expect(screen.getByText(/blueprint-4/)).toBeInTheDocument();
    expect(getJob).toHaveBeenCalledWith("job_blueprint_review");
    expect(getLatestBlueprint).toHaveBeenCalledTimes(2);
  });

  it("continues an approved blueprint into the Stage 2 batch dashboard", async () => {
    const user = userEvent.setup();
    const approved = structuredClone(blueprintView);
    approved.blueprint.status = "APPROVED";
    vi.mocked(getLatestBlueprint).mockResolvedValue(approved);

    render(
      <MemoryRouter initialEntries={["/activities/activity_01/blueprint"]}>
        <Route path="/activities/:activityId/blueprint"><BlueprintPage /></Route>
        <Route path="/activities/:activityId/submissions">
          <h1>Dashboard de lote E2</h1>
        </Route>
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: "Abrir lote de entregas" }),
    );
    expect(
      screen.getByRole("heading", { name: "Dashboard de lote E2" }),
    ).toBeInTheDocument();
  });

  it("persists every blocking P03 decision and resumes blueprint generation", async () => {
    const user = userEvent.setup();
    vi.mocked(getLatestBlueprint)
      .mockReset()
      .mockRejectedValueOnce(new ApiError(404, "Blueprint not found"))
      .mockResolvedValue(structuredClone(blueprintView));
    vi.mocked(getActivityAmbiguity).mockResolvedValue(structuredClone(ambiguityView));
    vi.mocked(getJob)
      .mockResolvedValueOnce({
        ...failedTechnicalJob,
        job_id: "job_ambiguity",
        aggregate_id: "activity_01",
        stage: "AMBIGUITY_TRIAGE",
        status: "NEEDS_REVIEW",
        progress: 0.45,
        attempt: 1,
        diagnostics: [],
      })
      .mockResolvedValue({
        ...failedTechnicalJob,
        job_id: "job_resumed",
        aggregate_id: "activity_01",
        stage: "BLUEPRINT_REVIEW",
        status: "SUCCEEDED",
        progress: 1,
        attempt: 1,
        diagnostics: [],
      });
    vi.mocked(createPolicyDecision).mockResolvedValue({
      schema_version: "1.1.0",
      decision_id: "decision_01",
      issue_id: "issue_scope",
      selected_option_id: "option_keep",
      decided_by: "user_01",
      decided_at: "2026-07-31T12:00:00Z",
    });
    vi.mocked(generateBlueprint).mockResolvedValue({
      ...failedTechnicalJob,
      job_id: "job_resumed",
      aggregate_id: "activity_01",
      status: "SUCCEEDED",
      diagnostics: [],
    });

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/activities/activity_01/blueprint",
            state: { jobId: "job_ambiguity" },
          },
        ]}
      >
        <Route path="/activities/:activityId/blueprint"><BlueprintPage /></Route>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Confirma las ambigüedades de la actividad" })).toBeInTheDocument();
    expect(screen.getByText("evidence_prompt_01")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Mantener alcance/ }));
    await user.click(screen.getByRole("button", { name: "Guardar y reanudar blueprint" }));

    await waitFor(() =>
      expect(createPolicyDecision).toHaveBeenCalledWith("activity_01", {
        issue_id: "issue_scope",
        selected_option_id: "option_keep",
      }),
    );
    expect(generateBlueprint).toHaveBeenCalledWith("activity_01");
  });

  it("recovers a queued activity after reload even when route state has no job id", async () => {
    vi.mocked(getLatestBlueprint)
      .mockReset()
      .mockRejectedValueOnce(new ApiError(404, "Blueprint not ready"))
      .mockResolvedValue(structuredClone(blueprintView));
    vi.mocked(getActivity).mockResolvedValue({
      schema_version: "1.1.0",
      activity_id: "activity_01",
      tenant_id: "tenant_01",
      title: "Actividad durable",
      output_language: "es-CL",
      assessment_modality: "WRITTEN",
      question_count: 1,
      target_total_minutes: 8,
      allowed_response_formats: ["OPEN_SHORT"],
      allowed_artifact_media_types: ["text/plain"],
      structured_justification_mode: "NOT_REQUIRED",
      context_mode: "CLOSED",
      course_source_ids: [],
      priority_criterion_ids: [],
      require_blueprint_approval: true,
      status: "QUEUED",
      created_at: "2026-07-31T12:00:00Z",
      updated_at: "2026-07-31T12:00:00Z",
      latest_blueprint_version: undefined,
      journey: {
        continue_path: "/activities/activity_01/blueprint",
        next_action: "VIEW_PROGRESS",
      },
    });

    render(
      <MemoryRouter initialEntries={["/activities/activity_01/blueprint"]}>
        <Route path="/activities/:activityId/blueprint"><BlueprintPage /></Route>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Comprensión causal" })).toBeInTheDocument();
    expect(getActivity).toHaveBeenCalledWith("activity_01");
    expect(getLatestBlueprint).toHaveBeenCalledTimes(2);
  });

  it("shows a persisted terminal failure instead of an endless loading state", async () => {
    vi.mocked(getLatestBlueprint)
      .mockReset()
      .mockRejectedValue(new ApiError(404, "Blueprint not available"));
    vi.mocked(getJob).mockResolvedValue({
      ...failedTechnicalJob,
      job_id: "job_failed",
      aggregate_id: "activity_01",
      stage: "BLUEPRINT_BUILD",
      status: "FAILED",
      progress: 0.7,
      attempt: 1,
      diagnostics: [
        { code: "BLUEPRINT_BUILD_FAILED", severity: "ERROR", message: "Fallo validado.", retryable: false },
      ],
    });

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/activities/activity_01/blueprint",
            state: { jobId: "job_failed" },
          },
        ]}
      >
        <Route path="/activities/:activityId/blueprint"><BlueprintPage /></Route>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "El pipeline no pudo completar el blueprint" })).toBeInTheDocument();
    expect(screen.getByText("BLUEPRINT_BUILD_FAILED")).toBeInTheDocument();
  });
});

describe("Stage 1 durable progress", () => {
  it("keeps the technical job state distinct from the submission domain state", () => {
    render(
      <MemoryRouter>
        <SubmissionProgress
          job={failedTechnicalJob}
          onOpenAssessment={vi.fn()}
          submission={submission}
        />
      </MemoryRouter>,
    );

    const statusPanels = screen.getByText("Job técnico").closest("section");
    expect(statusPanels).not.toBeNull();
    expect(within(statusPanels!).getByText("Falló")).toBeInTheDocument();
    expect(within(statusPanels!).getByText("Requiere revisión")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revisar evaluación" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reintentar|cancelar/i })).not.toBeInTheDocument();
  });
});

function ReviewHarness({ initialBundle = assessmentBundle }: { initialBundle?: AssessmentBundle }) {
  const [bundle, setBundle] = useState(structuredClone(initialBundle));
  const [tab, setTab] = useState<"assessment" | "guide">("assessment");
  const verified = (bundle.evidence_receipts ?? []).length > 0;
  return (
    <AssessmentReview
      allEvidenceVerified={verified}
      bundle={bundle}
      busy={false}
      exports={[]}
      onApprove={vi.fn()}
      onExport={vi.fn()}
      onTabChange={setTab}
      onVerify={(questionId, fragmentIndex) =>
        setBundle((current) => ({
          ...current,
          evidence_receipts: [
            {
              receipt_id: "receipt_01",
              assessment_id: current.assessment.assessment_id,
              assessment_version: current.assessment_version,
              assessment_etag: current.etag,
              question_id: questionId,
              fragment_index: fragmentIndex,
              evidence_id: "evidence_01",
              artifact_hash: `sha256:${"b".repeat(64)}`,
              locator_hash: `sha256:${"c".repeat(64)}`,
              normalized_hash: `sha256:${"a".repeat(64)}`,
              verified_at: "2026-07-31T12:00:00Z",
            },
          ],
        }))
      }
      tab={tab}
      verifying={null}
    />
  );
}

describe("Stage 1 evidence-first review", () => {
  it("shows provenance, semantic review and guide while keeping question actions out of scope", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ReviewHarness />
      </MemoryRouter>,
    );

    const assessmentTab = screen.getByRole("tab", { name: /Evaluación/ });
    assessmentTab.focus();
    await user.keyboard("{ArrowRight}");
    const guideTab = screen.getByRole("tab", { name: /Guía estructurada/ });
    expect(guideTab).toHaveFocus();
    expect(guideTab).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}");
    expect(assessmentTab).toHaveFocus();
    expect(assessmentTab).toHaveAttribute("aria-selected", "true");

    expect(screen.getAllByText("¿Cómo produjo la decisión descrita el efecto observado?")).toHaveLength(2);
    expect(screen.getByText("dimension: dim_causal")).toBeInTheDocument();
    expect(screen.getByText("variant: variant_tradeoff")).toBeInTheDocument();
    expect(screen.getByText("paragraph index: 3", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("QUESTION_GROUNDED")).toBeInTheDocument();
    expect(screen.getByText("Grounding")).toBeInTheDocument();

    const approve = screen.getByRole("button", { name: "Aprobar Assessment" });
    expect(approve).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Cargar y verificar fuente exacta" }));
    await waitFor(() => expect(approve).toBeEnabled());

    expect(screen.queryByRole("button", { name: /rechazar|editar pregunta|regenerar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /evaluación pdf|guía pdf|json canónico/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Guía estructurada/ }));
    const guidePanel = screen.getByRole("tabpanel", { name: /Guía estructurada/ });
    expect(within(guidePanel).getByText("Observar una explicación causal basada en la entrega.")).toBeInTheDocument();
    expect(within(guidePanel).getByText("Relaciona la decisión con su efecto y su trade-off.")).toBeInTheDocument();
    expect(within(guidePanel).getByText("Intención personal del estudiante.")).toBeInTheDocument();
  });

  it("separates every CHOICE alternative from evaluator-only answer metadata", async () => {
    const user = userEvent.setup();
    const choiceBundle = structuredClone(assessmentBundle);
    const question = choiceBundle.assessment.questions?.[0];
    if (!question) throw new Error("fixture must include one question");
    question.response_format = "CHOICE";
    question.choices = [
      {
        option_id: "option_a",
        text: "Mantener la deduplicación antes del promedio.",
        is_best_answer: true,
        evaluator_rationale: "Preserva el peso único de cada observación.",
        misconception: null,
      },
      {
        option_id: "option_b",
        text: "Promediar primero y deduplicar después.",
        is_best_answer: false,
        evaluator_rationale: "Duplica el peso antes de eliminar repeticiones.",
        misconception: "Confunde limpieza tardía con ponderación neutral.",
      },
      {
        option_id: "option_c",
        text: "Eliminar todos los valores extremos.",
        is_best_answer: false,
        evaluator_rationale: "La evidencia exige conservarlos y marcarlos.",
        misconception: "Asume que todo extremo es un error.",
      },
    ];

    render(
      <MemoryRouter>
        <ReviewHarness initialBundle={choiceBundle} />
      </MemoryRouter>,
    );

    const studentSection = screen.getByText("Contenido del estudiante").closest("section");
    const evaluatorSection = screen.getByText("Información del evaluador").closest("section");
    expect(studentSection).not.toBeNull();
    expect(evaluatorSection).not.toBeNull();
    expect(within(studentSection!).getAllByRole("listitem")).toHaveLength(3);
    expect(within(studentSection!).queryByText(/Mejor respuesta|error conceptual/)).not.toBeInTheDocument();
    expect(within(evaluatorSection!).getByText(/Mejor respuesta · option_a/)).toBeInTheDocument();
    expect(within(evaluatorSection!).getByText(/Confunde limpieza tardía/)).toBeInTheDocument();
    expect(screen.getByText("Justificación estudiantil: no requerida")).toBeInTheDocument();

    const approve = screen.getByRole("button", { name: "Aprobar Assessment" });
    expect(approve).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Cargar y verificar fuente exacta" }));
    await waitFor(() => expect(approve).toBeEnabled());
  });

  it("blocks approval when a CHOICE contract omits its alternatives", async () => {
    const user = userEvent.setup();
    const incomplete = structuredClone(assessmentBundle);
    const question = incomplete.assessment.questions?.[0];
    if (!question) throw new Error("fixture must include one question");
    question.response_format = "CHOICE";
    question.choices = [];
    render(
      <MemoryRouter>
        <ReviewHarness initialBundle={incomplete} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Una pregunta CHOICE no contiene alternativas evaluables completas",
    );
    const approve = screen.getByRole("button", { name: "Aprobar Assessment" });
    await user.click(screen.getByRole("button", { name: "Cargar y verificar fuente exacta" }));
    await waitFor(() => expect(approve).toBeDisabled());
  });
});
