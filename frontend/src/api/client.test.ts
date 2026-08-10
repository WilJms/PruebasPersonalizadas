import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assessmentBundle, blueprintView } from "../test/fixtures";
import {
  approveAssessment,
  createSubmissionBatch,
  createSubmissionUpload,
  createActivity,
  cancelJob,
  exchangeSession,
  getEvidence,
  getJobControl,
  login,
  resumeJob,
  retryJob,
  reviewQuestion,
  updateBlueprint,
} from "./client";

const session = {
  user_id: "user_01",
  email: "docente@example.test",
  workspace_id: "workspace_01",
  workspace_name: "Laboratorio",
  roles: ["TEACHER"],
};

describe("API client security defaults", () => {
  beforeEach(() => {
    document.cookie = "cva_csrf=; Max-Age=0; Path=/";
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the same-origin API, sends credentials and attaches the CSRF cookie", async () => {
    document.cookie = "cva_csrf=csrf-token-01; Path=/";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ session }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(login(session.email)).resolves.toEqual(session);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/v1/session/login");
    expect(init.credentials).toBe("include");
    expect(init.method).toBe("POST");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token-01");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-CVA-Shell-Epoch")).toBe("stage2-v1");
    expect(headers.has("Idempotency-Key")).toBe(false);
  });

  it("adds a fresh UUID Idempotency-Key to domain mutations", async () => {
    document.cookie = "cva_csrf=csrf-token-02; Path=/";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          activity: {
            activity_id: "activity_01",
            title: "Actividad",
            output_language: "es-CL",
            assessment_modality: "WRITTEN",
            question_count: 1,
            target_total_minutes: 5,
            allowed_response_formats: ["OPEN_SHORT"],
            allowed_artifact_media_types: ["text/plain"],
            structured_justification_mode: "NOT_REQUIRED",
            context_mode: "CLOSED",
            status: "DRAFT",
          },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createActivity({
      title: "Actividad",
      output_language: "es-CL",
      assessment_modality: "WRITTEN",
      question_count: 1,
      target_total_minutes: 5,
      allowed_response_formats: ["OPEN_SHORT"],
      allowed_artifact_media_types: ["text/plain"],
      structured_justification_mode: "NOT_REQUIRED",
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token-02");
  });

  it("exchanges a Supabase token without treating the session endpoint as a domain mutation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ session }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(exchangeSession("access-token-01")).resolves.toEqual(session);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/v1/session/exchange");
    expect(headers.get("Authorization")).toBe("Bearer access-token-01");
    expect(headers.has("Idempotency-Key")).toBe(false);
  });

  it("sends the assessment ETag together with idempotency on approval", async () => {
    document.cookie = "cva_csrf=csrf-token-03; Path=/";
    const approved = {
      ...assessmentBundle,
      etag: 'W/"assessment-2"',
      assessment: { ...assessmentBundle.assessment, status: "APPROVED" },
      evidence: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(approved), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      approveAssessment("assessment_01", 'W/"assessment-1"'),
    ).resolves.toMatchObject({ etag: 'W/"assessment-2"' });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("If-Match")).toBe('W/"assessment-1"');
    expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("starts durable blueprint review with If-Match and returns the accepted job", async () => {
    const job = {
      schema_version: "1.1.0",
      job_id: "job_blueprint_review_01",
      tenant_id: "tenant_01",
      aggregate_id: "activity_01",
      stage: "BLUEPRINT_REVIEW",
      status: "QUEUED",
      progress: 0,
      attempt: 1,
      diagnostics: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      updateBlueprint("activity_01", blueprintView.blueprint, blueprintView.etag),
    ).resolves.toEqual(job);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/v1/activities/activity_01/blueprints/3");
    expect(init.method).toBe("PATCH");
    expect(headers.get("If-Match")).toBe(blueprintView.etag);
    expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/i);
    expect(JSON.parse(String(init.body))).toEqual(blueprintView.blueprint);
  });

  it("follows evidence cursors until every signed source is loaded", async () => {
    const first = assessmentBundle.evidence?.[0];
    expect(first).toBeDefined();
    if (!first) throw new Error("fixture evidence missing");
    const second = { ...first, evidence_id: "evidence_02" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [first], next_cursor: "1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [second], next_cursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getEvidence("submission_01")).resolves.toEqual([first, second]);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/submissions/submission_01/evidence?limit=100&cursor=1",
      expect.any(Object),
    );
  });

  it("uses the Stage 2 batch endpoint with an exact pseudonymous list", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ submissions: [] }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createSubmissionBatch("activity_01", ["estudiante_014", "estudiante_015"]);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/activities/activity_01/submissions:batch");
    expect(JSON.parse(String(init.body))).toEqual({
      subject_refs: ["estudiante_014", "estudiante_015"],
    });
    expect(new Headers(init.headers).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("sends If-Match and the complete EDIT replacement to the question action endpoint", async () => {
    const question = assessmentBundle.assessment.questions?.[0];
    if (!question) throw new Error("fixture question missing");
    const replacement = { ...question, question_text: "Pregunta editada" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ record: { record_id: "record_01" } }), {
        status: 201,
        headers: { "Content-Type": "application/json", ETag: '"assessment-2"' },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await reviewQuestion(
      "assessment_01",
      question.question_id,
      { action: "EDIT", replacement },
      '"assessment-1"',
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1/assessments/assessment_01/questions/${question.question_id}/actions`);
    expect(new Headers(init.headers).get("If-Match")).toBe('"assessment-1"');
    expect(JSON.parse(String(init.body))).toEqual({ action: "EDIT", replacement });
  });

  it("identifies DOCX uploads with the OOXML media type even when the browser omits it", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ upload: {
        artifact_id: "artifact_01",
        upload_url: "/upload/artifact_01",
        expires_at: "2026-08-07T12:00:00Z",
        artifact: {},
      } }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["safe"], "entrega.docx", { type: "" });

    await createSubmissionUpload("submission_01", file);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({
      filename: "entrega.docx",
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
  });

  it("uses the durable control surface for retry, cancel and resume", async () => {
    const control = {
      job: {
        schema_version: "1.1.0",
        job_id: "job_01",
        tenant_id: "tenant_01",
        aggregate_id: "submission_01",
        stage: "PARSING",
        status: "FAILED",
        progress: 0.4,
        attempt: 1,
        diagnostics: [],
      },
      stage_runs: [],
      control_records: [],
      allowed_actions: ["RETRY"],
      control_state: "ACTIVE",
      failure_class: "TRANSIENT",
    };
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(control), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);

    await getJobControl("job_01");
    await retryJob("job_01");
    await cancelJob("job_01");
    await resumeJob("job_01");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/jobs/job_01/control",
      "/api/v1/jobs/job_01:retry",
      "/api/v1/jobs/job_01:cancel",
      "/api/v1/jobs/job_01:resume",
    ]);
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({ reason_code: "TEACHER_REQUESTED_RETRY" });
    expect(JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body))).toEqual({ reason_code: "TEACHER_REQUESTED_CANCEL" });
    expect(JSON.parse(String((fetchMock.mock.calls[3][1] as RequestInit).body))).toEqual({ reason_code: "TEACHER_REQUESTED_RESUME" });
  });
});
