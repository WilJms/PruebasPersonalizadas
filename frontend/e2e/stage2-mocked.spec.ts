import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const HASH = `sha256:${"a".repeat(64)}`;
const session = {
  user_id: "teacher_01",
  email: "teacher@example.test",
  workspace_id: "tenant_01",
  workspace_name: "Laboratorio E2",
  roles: ["TEACHER"],
};

const submissions = [
  {
    schema_version: "1.1.0",
    submission_id: "submission_upload",
    activity_id: "activity_01",
    subject_ref: "estudiante_015",
    status: "UPLOADED",
    current_stage: null,
    progress: 0,
    active_job_id: null,
    artifact_uploaded: false,
    assessment_id: null,
    diagnostics: [],
    updated_at: "2026-08-07T12:00:00Z",
  },
  {
    schema_version: "1.1.0",
    submission_id: "submission_01",
    activity_id: "activity_01",
    subject_ref: "estudiante_014",
    status: "NEEDS_REVIEW",
    current_stage: "QUESTION_VALIDATE",
    progress: 1,
    active_job_id: "job_01",
    artifact_uploaded: true,
    assessment_id: "assessment_01",
    assessment_version: 1,
    diagnostics: [],
    updated_at: "2026-08-07T12:00:00Z",
  },
];

const coverage = {
  schema_version: "1.2.0",
  report_id: "coverage_01",
  tenant_id: "tenant_01",
  activity_id: "activity_01",
  scope: "ACTIVITY",
  blueprint_id: "blueprint_01",
  blueprint_version: 3,
  source_snapshot_hash: HASH,
  summary: [{ dimension_id: "dim_causal", available_variant_count: 1, available_opportunity_count: 1, selected_opportunity_count: 1, reused_variant_count: 0, evidence_unit_count: 1, diagnostics: [] }],
  traces: [{ submission_id: "submission_01", assessment_id: "assessment_01", assessment_version: 1, dimension_id: "dim_causal", criterion_ids: ["criterion_01"], variant_id: "variant_tradeoff", opportunity_id: "opportunity_01", evidence_ids: ["evidence_01"], cognitive_operation: "EXPLAIN_MECHANISM", planning_role: "PRIMARY", outcome: "REVIEWED", reused_variant: false, diagnostics: [] }],
  diagnostics: [],
  generated_at: "2026-08-07T12:10:00Z",
};

const metrics = {
  schema_version: "1.2.0",
  metrics_id: "metrics_01",
  tenant_id: "tenant_01",
  activity_id: "activity_01",
  technical: { job_count: 2, succeeded_count: 1, failed_count: 1, cancelled_count: 0, retry_count: 1, latency_p50_ms: 1000, latency_p95_ms: 2000, input_tokens: 100, cached_input_tokens: 20, output_tokens: 30, estimated_cost_usd: 0.1, actual_cost_usd: 0.08 },
  quality: { assessment_count: 1, fail_closed_count: 0, defect_count: 0, exact_plan_count: 1, replacement_count: 0 },
  human_review: { reviewed_question_count: 1, accepted_count: 0, edited_count: 1, rejected_count: 0, regenerated_count: 0, review_seconds: 20 },
  by_stage: [], by_model: [], window_start: "2026-08-07T12:00:00Z", window_end: "2026-08-07T12:09:00Z", generated_at: "2026-08-07T12:10:00Z",
};

const guideDraft = {
  purpose: "Observar una explicación causal basada en la entrega.",
  observable_elements: [{
    element_id: "element_01",
    description: "Relaciona la decisión con su efecto y su trade-off.",
    evidence_ids: ["evidence_01"],
    source_ids: [],
    required_for_level_2: true,
  }],
  acceptance_conditions: ["Relaciona la decisión, el efecto y el trade-off con evidencia local."],
  acceptable_alternatives: ["Describe primero el efecto y luego reconstruye la causa."],
  misconceptions: ["Confundir correlación con causalidad."],
  levels: [
    { level: 0, label: "No observable", descriptor: "No usa la evidencia.", observable_element_ids: [] },
    { level: 1, label: "Parcial", descriptor: "Menciona decisión o efecto.", observable_element_ids: ["element_01"] },
    { level: 2, label: "Suficiente", descriptor: "Conecta decisión, efecto y costo.", observable_element_ids: ["element_01"] },
    { level: 3, label: "Profundo", descriptor: "Conecta y delimita la inferencia con precisión.", observable_element_ids: ["element_01"] },
  ],
  cannot_infer: ["Intención personal del estudiante."],
  semantic_uncertainties: ["La evidencia no permite generalizar fuera del caso."],
};

const approvedBundle = {
  etag: '"sha256:assessment-1"',
  assessment_version: 1,
  assessment: {
    schema_version: "1.1.0",
    assessment_id: "assessment_01",
    tenant_id: "tenant_01",
    activity_id: "activity_01",
    submission_id: "submission_01",
    subject_ref: "estudiante_014",
    status: "APPROVED",
    approved_by: "teacher_01",
    approved_at: "2026-08-07T12:05:00Z",
    context_mode: "CLOSED",
    assessment_plan_id: "assessment_plan_01",
    question_count: 1,
    questions: [{
      question_id: "question_01",
      source_candidate_id: "candidate_01",
      opportunity_id: "opportunity_01",
      opportunity_template_id: "opportunity_template_01",
      dimension_id: "dim_causal",
      variant_id: "variant_tradeoff",
      cognitive_operation: "EXPLAIN_MECHANISM",
      response_format: "OPEN_SHORT",
      difficulty: "MEDIUM",
      estimated_minutes: 8,
      question_text: "¿Cómo produjo la decisión descrita el efecto observado?",
      anchor: {
        anchor_id: "anchor_01",
        structure: "SINGLE_FRAGMENT",
        fragments: [{
          evidence_id: "evidence_01",
          display_text: "Se eligió el enfoque A para reducir la latencia.",
          transformation: "LITERAL",
          locator: { kind: "DOCUMENT_PATH", paragraph_index: 3 },
        }],
        self_containment_score: 0.92,
        answer_leakage_risk: 0.08,
      },
      evidence_ids: ["evidence_01"],
      course_source_ids: [],
      citations: [],
      choices: [],
      student_justification_required: false,
      preliminary_guide: guideDraft,
      planning_score: 0.91,
    }],
    coverage: [],
    structured_justification: {
      mode: "NOT_REQUIRED",
      required_question_ids: [],
      limited_evidence_notice_required: false,
    },
    diagnostics: [],
    created_at: "2026-08-07T12:00:00Z",
  },
  guide: {
    schema_version: "1.1.0",
    guide_id: "guide_01",
    assessment_id: "assessment_01",
    submission_id: "submission_01",
    status: "READY",
    items: [{ question_id: "question_01", guide: guideDraft }],
    diagnostics: [],
    created_at: "2026-08-07T12:00:00Z",
  },
  guide_status: "READY",
  guide_job_id: "job_guide_01",
  reviews: [],
  evidence: [{
    schema_version: "1.1.0",
    evidence_id: "evidence_01",
    tenant_id: "tenant_01",
    submission_id: "submission_01",
    artifact_id: "artifact_01",
    artifact_hash: HASH,
    source_role: "SUBMISSION",
    modality: "PARAGRAPH",
    locator: { kind: "DOCUMENT_PATH", paragraph_index: 3 },
    content_text: "Se eligió el enfoque A para reducir la latencia.",
    extraction_confidence: 0.99,
    ocr_used: false,
    relations: [],
    sensitive_labels: [],
    normalized_hash: HASH,
  }],
  evidence_receipts: [],
};

const exportRecord = {
  schema_version: "1.2.0",
  export_id: "export_01",
  tenant_id: "tenant_01",
  activity_id: "activity_01",
  assessment_id: "assessment_01",
  assessment_version: 1,
  requested_by: "teacher_01",
  requested_kinds: ["ASSESSMENT_PDF", "CANONICAL_JSON"],
  status: "READY",
  assessment_snapshot_hash: HASH,
  guide_snapshot_hash: HASH,
  coverage_snapshot_hash: HASH,
  renderer_version: "renderer-2.0.0",
  artifacts: [],
  model_call_delta: 0,
  diagnostics: [],
  requested_at: "2026-08-07T12:04:00Z",
  completed_at: "2026-08-07T12:04:04Z",
};

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installMocks(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (path === "/session") return fulfill(route, { session });
    if (path === "/activities/activity_01/submissions" && method === "GET") return fulfill(route, { items: submissions });
    if (path === "/activities/activity_01/submissions:batch") return fulfill(route, { submissions: [] }, 201);
    if (path === "/activities/activity_01/coverage") return fulfill(route, { coverage });
    if (path === "/activities/activity_01/metrics") return fulfill(route, { metrics });
    if (path === "/activities/activity_01/feedback") return fulfill(route, { items: [] });
    if (path === "/activities/activity_01/bulk-approvals") return fulfill(route, { items: [] });
    if (path === "/submissions/submission_01/assessment") return fulfill(route, approvedBundle);
    if (path === "/submissions/submission_01/evidence") return fulfill(route, { items: approvedBundle.evidence });
    if (path === "/submissions/submission_01/coverage") return fulfill(route, { coverage });
    if (path === "/assessments/assessment_01/exports" && method === "GET") return fulfill(route, { items: [exportRecord] });
    if (path === "/assessments/assessment_01/questions/question_01/actions" && method === "GET") return fulfill(route, { items: [] });
    if (path === "/feedback") return fulfill(route, { feedback: { feedback_id: "feedback_01", tenant_id: "tenant_01", actor_id: "teacher_01", training_use_allowed: false, public_dataset_use_allowed: false, academic_decision_use_allowed: false, created_at: "2026-08-07T12:12:00Z", ...request.postDataJSON() } }, 201);
    if (path === "/activities/activity_01/assessments:bulk-approve") return fulfill(route, { approval: { schema_version: "1.1.0", approval_id: "approval_01", request_id: "request_01", tenant_id: "tenant_01", actor_id: "teacher_01", scope: "SELECTED_ELIGIBLE_ASSESSMENTS", approved_at: "2026-08-07T12:12:00Z", requested_targets: [{ assessment_id: "assessment_01", assessment_version: 1 }], approved_targets: [{ assessment_id: "assessment_01", assessment_version: 1 }], excluded_targets: [] } }, 201);
    return fulfill(route, { detail: `Unexpected mocked route: ${method} ${path}` }, 404);
  });
}

async function expectNoSeriousA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations.filter((item) => item.impact === "critical" || item.impact === "serious")).toEqual([]);
}

test("manual batch dashboard is keyboard navigable and keeps critical guardrails visible", async ({ page }) => {
  await installMocks(page);
  await page.goto("/activities/activity_01/lab");
  await expect(page.getByRole("heading", { name: "Lote de entregas" })).toBeVisible();
  await expect(page.getByText(/no detecta IA/i)).toContainText("la decisión académica sigue siendo humana");
  await expect(page.getByLabel("Elegir archivo para estudiante_015")).toHaveAttribute("accept", /docx/);

  const firstTab = page.getByRole("tab", { name: /Entregas/ });
  await firstTab.focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: /Feedback/ })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(firstTab).toBeFocused();
  await page.getByRole("tab", { name: "Cobertura" }).click();
  await expect(page.getByRole("heading", { name: "Cobertura trazable" })).toBeVisible();
  await expectNoSeriousA11yViolations(page);

  await page.setViewportSize({ width: 390, height: 780 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("approved assessment review contains its export history on a 390px viewport", async ({ page }) => {
  const browserProblems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      browserProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => browserProblems.push(`pageerror: ${error.message}`));

  await page.setViewportSize({ width: 390, height: 844 });
  await installMocks(page);
  await page.goto("/submissions/submission_01/review");

  await expect(page).toHaveURL(/\/submissions\/submission_01\/review$/);
  expect(await page.title()).not.toBe("");
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Revisión basada en evidencia" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Historial de exportaciones derivadas" })).toBeVisible();
  await expect.poll(
    () => page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  const exportScroller = page.getByLabel("Historial desplazable de exportaciones");
  const scrollerBounds = await exportScroller.boundingBox();
  expect(scrollerBounds).not.toBeNull();
  expect(scrollerBounds!.x + scrollerBounds!.width).toBeLessThanOrEqual(390);
  await expect.poll(
    () => exportScroller.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    ),
  ).toBe(true);

  const assessmentTab = page.getByRole("tab", { name: /Evaluación/ });
  await assessmentTab.focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: /Guía estructurada/ })).toBeFocused();
  await expectNoSeriousA11yViolations(page);
  expect(browserProblems).toEqual([]);

  await page.setViewportSize({ width: 1280, height: 900 });
  await expect.poll(
    () => page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(1280);
});
