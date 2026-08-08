import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelJob,
  getJobControl,
  resumeJob,
  retryJob,
} from "../api/client";
import type { JobControlView } from "../api/types";
import { JobControlPanel } from "./JobControlPanel";

vi.mock("../api/client", () => ({
  cancelJob: vi.fn(),
  getJobControl: vi.fn(),
  resumeJob: vi.fn(),
  retryJob: vi.fn(),
}));

const baseView: JobControlView = {
  job: {
    schema_version: "1.1.0",
    job_id: "job_01",
    tenant_id: "tenant_01",
    aggregate_id: "submission_01",
    stage: "VALIDATING_QUESTIONS",
    status: "NEEDS_REVIEW",
    progress: 0.8,
    attempt: 2,
    diagnostics: [],
  },
  stage_runs: [
    {
      schema_version: "1.2.0",
      stage_run_id: "stage_run_01",
      tenant_id: "tenant_01",
      job_id: "job_01",
      aggregate_id: "submission_01",
      stage: "PARSING",
      stage_key: `sha256:${"a".repeat(64)}`,
      input_hash: `sha256:${"b".repeat(64)}`,
      policy_hash: `sha256:${"c".repeat(64)}`,
      component_version: "parser-v2",
      status: "SUCCEEDED",
      attempt: 1,
      retryable: false,
      output_ref: "database/stage_outputs/stage_run_01",
      output_hash: `sha256:${"d".repeat(64)}`,
      diagnostics: [],
      created_at: "2026-08-07T12:00:00Z",
      started_at: "2026-08-07T12:00:00Z",
      finished_at: "2026-08-07T12:00:02Z",
    },
    {
      schema_version: "1.2.0",
      stage_run_id: "stage_run_02",
      tenant_id: "tenant_01",
      job_id: "job_01",
      aggregate_id: "submission_01",
      stage: "VALIDATING_QUESTIONS",
      stage_key: `sha256:${"e".repeat(64)}`,
      input_hash: `sha256:${"f".repeat(64)}`,
      policy_hash: `sha256:${"1".repeat(64)}`,
      component_version: "validator-v2",
      status: "FAILED",
      attempt: 2,
      retryable: false,
      failure_class: "VALIDATION",
      diagnostics: [{ code: "QUESTION_INVALID", severity: "ERROR", message: "La pregunta requiere revisión.", evidence_ids: [], source_ids: [], retryable: false, details: {} }],
      created_at: "2026-08-07T12:00:03Z",
      started_at: "2026-08-07T12:00:03Z",
      finished_at: "2026-08-07T12:00:04Z",
    },
  ],
  control_records: [],
  allowed_actions: ["RESUME"],
  resumable_stage: "VALIDATING_QUESTIONS",
  control_state: "ACTIVE",
  failure_class: "VALIDATION",
};

describe("JobControlPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders stage runs, honors server actions and moves focus to durable feedback", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const resumed: JobControlView = {
      ...baseView,
      job: {
        ...baseView.job,
        job_id: "job_resume_01",
        status: "QUEUED",
        progress: 0,
        attempt: 3,
      },
      allowed_actions: ["CANCEL"],
    };
    vi.mocked(getJobControl).mockResolvedValue(baseView);
    vi.mocked(resumeJob).mockResolvedValue(resumed);

    render(<JobControlPanel jobId="job_01" onChange={onChange} />);

    const stageRuns = await screen.findByRole("list", { name: "Ejecuciones por etapa" });
    expect(within(stageRuns).getAllByRole("listitem")).toHaveLength(2);
    expect(within(stageRuns).getByText("PARSING")).toBeInTheDocument();
    expect(within(stageRuns).getByText("VALIDATING QUESTIONS")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reanudar job" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Reintentar job" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar job" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reanudar job" }));

    expect(resumeJob).toHaveBeenCalledWith("job_01");
    expect(onChange).toHaveBeenCalledWith(resumed);
    const feedback = await screen.findByRole("status");
    expect(feedback).toHaveTextContent("La reanudación quedó solicitada y persistida.");
    await waitFor(() => expect(feedback).toHaveFocus());
    expect(screen.getByRole("button", { name: "Cancelar job" })).toBeEnabled();
  });

  it("honors an explicit cancel capability and focuses errors", async () => {
    const user = userEvent.setup();
    vi.mocked(getJobControl).mockResolvedValue({
      ...baseView,
      job: { ...baseView.job, status: "RUNNING" },
      allowed_actions: ["CANCEL"],
    });
    vi.mocked(cancelJob).mockRejectedValue(new Error("El job ya terminó."));

    render(<JobControlPanel jobId="job_02" />);

    const cancel = await screen.findByRole("button", { name: "Cancelar job" });
    expect(screen.queryByRole("button", { name: "Reanudar job" })).not.toBeInTheDocument();
    expect(retryJob).not.toHaveBeenCalled();
    await user.click(cancel);

    expect(cancelJob).toHaveBeenCalledWith("job_02");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("El job ya terminó.");
    await waitFor(() => expect(alert).toHaveFocus());
    expect(cancel).toBeEnabled();
  });
});
