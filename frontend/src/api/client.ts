import type {
  ActivityCreateInput,
  ActivityResource,
  ActivityUpdateInput,
  AmbiguityView,
  ArtifactResource,
  AssessmentBlueprint,
  AssessmentBundle,
  EvaluationGuide,
  ExportKind,
  ExportResource,
  JobStatus,
  PolicyDecision,
  Session,
  StartedOperation,
  SubmissionResource,
  UploadSession,
  BlueprintView,
  EvidenceUnit,
  EvidenceVerification,
  CostEstimate,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");

type JsonObject = Record<string, unknown>;

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const prefix = `${encodeURIComponent(name)}=`;
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (!match) return undefined;
  try {
    return decodeURIComponent(match.slice(prefix.length));
  } catch {
    return match.slice(prefix.length);
  }
}

function unwrap<T>(value: unknown): T {
  if (value && typeof value === "object" && "data" in value) {
    return (value as { data: T }).data;
  }
  return value as T;
}

function pick<T>(value: unknown, key: string): T {
  const unwrapped = unwrap<unknown>(value);
  if (unwrapped && typeof unwrapped === "object" && key in unwrapped) {
    return (unwrapped as JsonObject)[key] as T;
  }
  return unwrapped as T;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) return text;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiError(response.status, "La respuesta del servidor no es JSON válido.");
  }
}

function errorFrom(response: Response, body: unknown): ApiError {
  if (body && typeof body === "object") {
    const problem = body as JsonObject;
    const detail =
      typeof problem.detail === "string"
        ? problem.detail
        : typeof problem.message === "string"
          ? problem.message
          : undefined;
    return new ApiError(
      response.status,
      detail ?? `La solicitud falló (${response.status}).`,
      typeof problem.code === "string" ? problem.code : undefined,
    );
  }
  return new ApiError(response.status, `La solicitud falló (${response.status}).`);
}

function isMutating(method: string): boolean {
  return ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
}

function isDomainMutation(path: string, method: string): boolean {
  return ["POST", "PATCH", "DELETE"].includes(method.toUpperCase()) &&
    !path.startsWith("/session/");
}

function idempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID !== "function") {
    throw new Error("Este navegador no puede generar claves de idempotencia seguras.");
  }
  return globalThis.crypto.randomUUID();
}

async function requestWithMeta<T>(
  path: string,
  init: RequestInit = {},
): Promise<{ data: T; etag?: string }> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isMutating(method)) {
    const csrf = readCookie("cva_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  if (isDomainMutation(path, method) && !headers.has("Idempotency-Key")) {
    headers.set("Idempotency-Key", idempotencyKey());
  }
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });
  const body = await parseBody(response);
  if (!response.ok) throw errorFrom(response, body);
  return {
    data: unwrap<T>(body),
    etag: response.headers.get("etag") ?? undefined,
  };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await requestWithMeta<T>(path, init)).data;
}

export async function getSession(): Promise<Session> {
  const result = await request<unknown>("/session");
  return pick<Session>(result, "session");
}

export async function login(email: string): Promise<Session> {
  const result = await request<unknown>("/session/login", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  return pick<Session>(result, "session");
}

export async function exchangeSession(accessToken: string): Promise<Session> {
  const result = await request<unknown>("/session/exchange", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({}),
  });
  return pick<Session>(result, "session");
}

export async function logout(): Promise<void> {
  await request("/session/logout", { method: "POST" });
}

export async function createActivity(
  payload: ActivityCreateInput,
): Promise<ActivityResource> {
  const result = await request<unknown>("/activities", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return pick<ActivityResource>(result, "activity");
}

export async function getActivity(activityId: string): Promise<ActivityResource> {
  const result = await request<unknown>(`/activities/${activityId}`);
  return pick<ActivityResource>(result, "activity");
}

export async function listActivities(): Promise<ActivityResource[]> {
  const result = await request<unknown>("/activities");
  return pick<ActivityResource[]>(result, "items");
}

export async function getActivityWithEtag(
  activityId: string,
): Promise<{ activity: ActivityResource; etag: string }> {
  const result = await requestWithMeta<unknown>(`/activities/${activityId}`);
  if (!result.etag) {
    throw new ApiError(500, "La actividad no incluyó el ETag requerido para editar.");
  }
  return { activity: pick<ActivityResource>(result.data, "activity"), etag: result.etag };
}

export async function updateActivity(
  activityId: string,
  payload: ActivityUpdateInput,
  etag: string,
): Promise<{ activity: ActivityResource; etag: string }> {
  const result = await requestWithMeta<unknown>(`/activities/${activityId}`, {
    method: "PATCH",
    headers: { "If-Match": etag },
    body: JSON.stringify(payload),
  });
  if (!result.etag) {
    throw new ApiError(500, "La actividad editada no incluyó su nuevo ETag.");
  }
  return { activity: pick<ActivityResource>(result.data, "activity"), etag: result.etag };
}

export async function createActivityUpload(
  activityId: string,
  role: "ASSIGNMENT_PROMPT" | "RUBRIC",
  file: File,
): Promise<UploadSession> {
  const result = await request<unknown>(`/activities/${activityId}/artifacts/uploads`, {
    method: "POST",
    body: JSON.stringify({
      role,
      filename: file.name,
      media_type: mediaTypeFor(file),
      byte_size: file.size,
    }),
  });
  return pick<UploadSession>(result, "upload");
}

export async function completeActivityUpload(
  activityId: string,
  upload: UploadSession,
  file: File,
): Promise<ArtifactResource> {
  await putSignedUpload(upload, file);
  const sha256 = await sha256File(file);
  const result = await request<unknown>(
    `/activities/${activityId}/artifacts/${upload.artifact_id}:complete`,
    {
      method: "POST",
      body: JSON.stringify({
        sha256,
        byte_size: file.size,
        media_type: mediaTypeFor(file),
      }),
    },
  );
  return pick<ArtifactResource>(result, "artifact");
}

export async function uploadActivityArtifact(
  activityId: string,
  role: "ASSIGNMENT_PROMPT" | "RUBRIC",
  file: File,
): Promise<ArtifactResource> {
  const upload = await createActivityUpload(activityId, role, file);
  return completeActivityUpload(activityId, upload, file);
}

export async function generateBlueprint(activityId: string): Promise<StartedOperation> {
  const result = await request<unknown>(`/activities/${activityId}/blueprints:generate`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  return pick<StartedOperation>(result, "operation");
}

export async function getActivityEstimate(activityId: string): Promise<CostEstimate> {
  const result = await request<unknown>(`/activities/${activityId}/estimate`);
  return pick<CostEstimate>(result, "estimate");
}

export async function getActivityAmbiguity(activityId: string): Promise<AmbiguityView> {
  return request<AmbiguityView>(`/activities/${activityId}/ambiguity`);
}

export async function createPolicyDecision(
  activityId: string,
  input: { issue_id: string; selected_option_id: string; note?: string },
): Promise<PolicyDecision> {
  const result = await request<unknown>(`/activities/${activityId}/decisions`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return pick<PolicyDecision>(result, "decision");
}

function normalizeBlueprintView(
  value: unknown,
  headerEtag?: string,
): BlueprintView {
  const data = unwrap<unknown>(value);
  if (data && typeof data === "object" && "blueprint" in data) {
    const view = data as BlueprintView;
    return {
      ...view,
      etag: headerEtag ?? view.etag ?? `W/\"${view.blueprint.blueprint_version}\"`,
    };
  }
  const blueprint = data as AssessmentBlueprint;
  return {
    blueprint,
    etag: headerEtag ?? `W/\"${blueprint.blueprint_version}\"`,
    version: blueprint.blueprint_version,
  };
}

export async function getLatestBlueprint(activityId: string): Promise<BlueprintView> {
  try {
    const result = await requestWithMeta<unknown>(
      `/activities/${activityId}/blueprints/latest`,
    );
    return normalizeBlueprintView(result.data, result.etag);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error;
    const activity = await getActivity(activityId);
    if (!activity.latest_blueprint_version) throw error;
    return getBlueprint(activityId, activity.latest_blueprint_version);
  }
}

export async function getBlueprint(
  activityId: string,
  version: number,
): Promise<BlueprintView> {
  const result = await requestWithMeta<unknown>(
    `/activities/${activityId}/blueprints/${version}`,
  );
  return normalizeBlueprintView(result.data, result.etag);
}

export async function updateBlueprint(
  activityId: string,
  blueprint: AssessmentBlueprint,
  etag: string,
): Promise<BlueprintView> {
  const result = await requestWithMeta<unknown>(
    `/activities/${activityId}/blueprints/${blueprint.blueprint_version}`,
    {
      method: "PATCH",
      headers: { "If-Match": etag },
      body: JSON.stringify(blueprint),
    },
  );
  return normalizeBlueprintView(result.data, result.etag);
}

export async function approveBlueprint(
  activityId: string,
  blueprint: AssessmentBlueprint,
  etag: string,
): Promise<BlueprintView> {
  const result = await requestWithMeta<unknown>(
    `/activities/${activityId}/blueprints/${blueprint.blueprint_version}:approve`,
    {
      method: "POST",
      headers: { "If-Match": etag },
      body: JSON.stringify({}),
    },
  );
  return normalizeBlueprintView(result.data, result.etag);
}

export async function createSubmission(
  activityId: string,
  subjectRef: string,
): Promise<SubmissionResource> {
  const result = await request<unknown>(`/activities/${activityId}/submissions`, {
    method: "POST",
    body: JSON.stringify({ subject_ref: subjectRef }),
  });
  return pick<SubmissionResource>(result, "submission");
}

export async function createSubmissionUpload(
  submissionId: string,
  file: File,
): Promise<UploadSession> {
  const result = await request<unknown>(`/submissions/${submissionId}/artifacts/uploads`, {
    method: "POST",
    body: JSON.stringify({
      role: "SUBMISSION",
      filename: file.name,
      media_type: mediaTypeFor(file),
      byte_size: file.size,
    }),
  });
  return pick<UploadSession>(result, "upload");
}

export async function uploadSubmissionArtifact(
  submissionId: string,
  file: File,
): Promise<ArtifactResource> {
  const upload = await createSubmissionUpload(submissionId, file);
  await putSignedUpload(upload, file);
  const sha256 = await sha256File(file);
  const result = await request<unknown>(
    `/submissions/${submissionId}/artifacts/${upload.artifact_id}:complete`,
    {
      method: "POST",
      body: JSON.stringify({
        sha256,
        byte_size: file.size,
        media_type: mediaTypeFor(file),
      }),
    },
  );
  return pick<ArtifactResource>(result, "artifact");
}

export async function runSubmission(submissionId: string): Promise<StartedOperation> {
  const result = await request<unknown>(`/submissions/${submissionId}:run`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  return pick<StartedOperation>(result, "operation");
}

export async function getSubmissionEstimate(submissionId: string): Promise<CostEstimate> {
  const result = await request<unknown>(`/submissions/${submissionId}/estimate`);
  return pick<CostEstimate>(result, "estimate");
}

export async function getSubmission(submissionId: string): Promise<SubmissionResource> {
  const result = await request<unknown>(`/submissions/${submissionId}`);
  return pick<SubmissionResource>(result, "submission");
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const result = await request<unknown>(`/jobs/${jobId}`);
  return pick<JobStatus>(result, "job");
}

export async function getEvidence(submissionId: string): Promise<EvidenceUnit[]> {
  const collected: EvidenceUnit[] = [];
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ limit: "100" });
    if (cursor) query.set("cursor", cursor);
    const result = await request<unknown>(
      `/submissions/${submissionId}/evidence?${query.toString()}`,
    );
    const data = unwrap<unknown>(result);
    if (Array.isArray(data)) return data as EvidenceUnit[];
    if (data && typeof data === "object" && "items" in data) {
      const page = data as { items: EvidenceUnit[]; next_cursor?: string | null };
      collected.push(...page.items);
      cursor = page.next_cursor ?? null;
    } else {
      return pick<EvidenceUnit[]>(data, "evidence");
    }
  } while (cursor);
  return collected;
}

export async function getAssessmentBundle(
  submissionId: string,
): Promise<AssessmentBundle> {
  const result = await request<unknown>(`/submissions/${submissionId}/assessment`);
  const data = unwrap<unknown>(result);
  if (data && typeof data === "object" && "assessment" in data) {
    const bundle = data as AssessmentBundle;
    if (!bundle.etag) {
      throw new ApiError(500, "La evaluación no incluyó el ETag requerido para revisión.");
    }
    return {
      assessment: bundle.assessment,
      reviews: bundle.reviews ?? [],
      evidence: bundle.evidence ?? [],
      evidence_receipts: bundle.evidence_receipts ?? [],
      guide: bundle.guide,
      etag: bundle.etag,
      assessment_version: bundle.assessment_version,
    };
  }
  throw new ApiError(500, "La respuesta de evaluación no tiene el contrato esperado.");
}

export async function getGuide(assessmentId: string): Promise<EvaluationGuide> {
  const result = await request<unknown>(`/assessments/${assessmentId}/guide`);
  return pick<EvaluationGuide>(result, "guide");
}

export async function verifyEvidenceFragment(
  assessmentId: string,
  input: {
    assessment_version: number;
    assessment_etag: string;
    question_id: string;
    fragment_index: number;
  },
): Promise<EvidenceVerification> {
  const result = await request<unknown>(`/assessments/${assessmentId}/evidence:verify`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return pick<EvidenceVerification>(result, "verification");
}

export async function approveAssessment(
  assessmentId: string,
  etag: string,
): Promise<AssessmentBundle> {
  const result = await request<unknown>(`/assessments/${assessmentId}:approve`, {
    method: "POST",
    headers: { "If-Match": etag },
    body: JSON.stringify({}),
  });
  const data = unwrap<unknown>(result);
  if (data && typeof data === "object" && "assessment" in data) {
    const bundle = data as AssessmentBundle;
    if (!bundle.etag) {
      throw new ApiError(500, "La aprobación no devolvió el ETag de la versión aprobada.");
    }
    return {
      assessment: bundle.assessment,
      reviews: bundle.reviews ?? [],
      evidence: bundle.evidence ?? [],
      evidence_receipts: bundle.evidence_receipts ?? [],
      guide: bundle.guide,
      etag: bundle.etag,
      assessment_version: bundle.assessment_version,
    };
  }
  throw new ApiError(500, "La respuesta de aprobación no tiene el contrato esperado.");
}

export async function createExport(
  assessmentId: string,
  kind: ExportKind,
): Promise<ExportResource> {
  const result = await request<unknown>(`/assessments/${assessmentId}/exports`, {
    method: "POST",
    body: JSON.stringify({ kind }),
  });
  return pick<ExportResource>(result, "export");
}

async function putSignedUpload(upload: UploadSession, file: File): Promise<void> {
  const response = await fetch(upload.upload_url, {
    method: "PUT",
    headers: {
      "Content-Type": mediaTypeFor(file),
      ...(upload.upload_headers ?? {}),
    },
    body: file,
    credentials: upload.upload_url.startsWith("/") ? "include" : "omit",
  });
  if (!response.ok) {
    throw new ApiError(response.status, "No se pudo transferir el archivo al almacenamiento privado.");
  }
}

function mediaTypeFor(file: File): string {
  if (file.type) return file.type;
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".pdf")) return "application/pdf";
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "text/markdown";
  return "text/plain";
}

async function sha256File(file: File): Promise<string> {
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `sha256:${hex}`;
}
