import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  approveBlueprint,
  createPolicyDecision,
  generateBlueprint,
  getActivity,
  getActivityAmbiguity,
  getJob,
  getLatestBlueprint,
  updateBlueprint,
} from "../api/client";
import {
  ambiguityView,
  assessmentBundle,
  blueprintView,
  evaluationGuide,
  failedTechnicalJob,
  submission,
} from "../test/fixtures";
import { ActivityCreatePage } from "./ActivityCreatePage";
import { AssessmentReview } from "./AssessmentReviewPage";
import { BlueprintPage } from "./BlueprintPage";
import { SubmissionProgress } from "./SubmissionPage";

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
    getLatestBlueprint: vi.fn(),
    updateBlueprint: vi.fn(),
  };
});

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

describe("Stage 1 blueprint review", () => {
  beforeEach(() => {
    vi.mocked(getLatestBlueprint).mockReset().mockResolvedValue(structuredClone(blueprintView));
    vi.mocked(getJob).mockReset();
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
        <Routes>
          <Route path="/activities/:activityId/blueprint" element={<BlueprintPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Comprensión causal" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Decisión con trade-off" })).toBeInTheDocument();
    expect(screen.getAllByText("EXPLAIN CAUSALLY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Efecto de la decisión principal")).toBeInTheDocument();
    expect(screen.getByText(/blueprint-3/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Editar blueprint" }));
    expect(screen.getByRole("textbox", { name: "Nombre de dimensión 1" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Foco opp_01" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /operación/i })).not.toBeInTheDocument();
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
        job_id: "job_ambiguity",
        stage: "AMBIGUITY_TRIAGE",
        status: "NEEDS_REVIEW",
        progress: 0.45,
        attempt: 1,
      })
      .mockResolvedValue({
        job_id: "job_resumed",
        stage: "BLUEPRINT_REVIEW",
        status: "SUCCEEDED",
        progress: 1,
        attempt: 1,
      });
    vi.mocked(createPolicyDecision).mockResolvedValue({
      schema_version: "1.1",
      decision_id: "decision_01",
      issue_id: "issue_scope",
      selected_option_id: "option_keep",
      decided_by: "user_01",
      decided_at: "2026-07-31T12:00:00Z",
    });
    vi.mocked(generateBlueprint).mockResolvedValue({ job_id: "job_resumed" });

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/activities/activity_01/blueprint",
            state: { jobId: "job_ambiguity" },
          },
        ]}
      >
        <Routes>
          <Route path="/activities/:activityId/blueprint" element={<BlueprintPage />} />
        </Routes>
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
      ...blueprintView.blueprint.assessment_constraints,
      activity_id: "activity_01",
      title: "Actividad durable",
      output_language: "es-CL",
      assessment_modality: "WRITTEN",
      allowed_artifact_media_types: ["text/plain"],
      structured_justification_mode: "NOT_REQUIRED",
      context_mode: "CLOSED",
      status: "QUEUED",
    });

    render(
      <MemoryRouter initialEntries={["/activities/activity_01/blueprint"]}>
        <Routes>
          <Route path="/activities/:activityId/blueprint" element={<BlueprintPage />} />
        </Routes>
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
      job_id: "job_failed",
      stage: "BLUEPRINT_BUILD",
      status: "FAILED",
      progress: 0.7,
      attempt: 1,
      diagnostics: [
        { code: "BLUEPRINT_BUILD_FAILED", severity: "ERROR", message: "Fallo validado." },
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
        <Routes>
          <Route path="/activities/:activityId/blueprint" element={<BlueprintPage />} />
        </Routes>
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

function ReviewHarness() {
  const [opened, setOpened] = useState(false);
  const [tab, setTab] = useState<"assessment" | "guide">("assessment");
  return (
    <AssessmentReview
      allEvidenceOpened={opened}
      bundle={assessmentBundle}
      busy={false}
      exports={[]}
      guide={evaluationGuide}
      onApprove={vi.fn()}
      onEvidenceOpened={() => setOpened(true)}
      onExport={vi.fn()}
      onTabChange={setTab}
      tab={tab}
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

    expect(screen.getByText("¿Cómo produjo la decisión descrita el efecto observado?")).toBeInTheDocument();
    expect(screen.getAllByText("dim_causal").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("variant_tradeoff")).toBeInTheDocument();
    expect(screen.getByText("page: 3", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("QUESTION_GROUNDED")).toBeInTheDocument();
    expect(screen.getByText("Grounding")).toBeInTheDocument();

    const approve = screen.getByRole("button", { name: "Aprobar Assessment" });
    expect(approve).toBeDisabled();
    await user.click(screen.getByRole("link", { name: "Abrir fuente exacta" }));
    await waitFor(() => expect(approve).toBeEnabled());

    expect(screen.queryByRole("button", { name: /rechazar|editar pregunta|regenerar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /evaluación pdf|guía pdf|json canónico/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Guía estructurada/ }));
    expect(screen.getByText("Observar una explicación causal basada en la entrega.")).toBeInTheDocument();
    expect(screen.getByText("Relaciona la decisión con su efecto y su trade-off.")).toBeInTheDocument();
    expect(screen.getByText("Intención personal del estudiante.")).toBeInTheDocument();
  });
});
