import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assessmentBundle } from "../test/fixtures";
import {
  approveAssessment,
  createActivity,
  exchangeSession,
  getEvidence,
  login,
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
});
