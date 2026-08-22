import type {
  AssessmentBundle,
  AmbiguityView,
  BlueprintView,
  EvaluationGuide,
  JobStatus,
  SubmissionResource,
} from "../api/types";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;

export const ambiguityView: AmbiguityView = {
  report: {
    schema_version: "1.1.0",
    activity_id: "activity_01",
    blocked: true,
    issues: [
      {
        issue_id: "issue_scope",
        issue_code: "ASSIGNMENT_AMBIGUOUS",
        severity: "ERROR",
        evidence_ids: ["evidence_prompt_01"],
        explanation: "El alcance debe ser confirmado por una persona docente.",
        options: [
          { option_id: "option_keep", label: "Mantener alcance", consequence: "Conserva el alcance explícito." },
          { option_id: "option_narrow", label: "Acotar alcance", consequence: "Limita la verificación." },
        ],
        recommended_option_id: "option_keep",
        blocking: true,
      },
    ],
  },
  decisions: [],
};

export const blueprintView: BlueprintView = {
  etag: '"sha256:blueprint-3"',
  version: 3,
  blueprint: {
    schema_version: "1.1.0",
    blueprint_id: "blueprint_01",
    blueprint_version: 3,
    activity_id: "activity_01",
    status: "READY",
    context_mode: "CLOSED",
    assessment_constraints: {
      question_count: 1,
      target_total_minutes: 8,
      allowed_response_formats: ["OPEN_SHORT"],
      minimum_opportunity_quality: 0.75,
      max_reserve_opportunities: 3,
      structured_justification_policy: {
        mode: "NOT_REQUIRED",
        selected_opportunity_template_ids: [],
      },
    },
    decision_ids: [],
    diagnostics: [],
    dimensions: [
      {
        dimension_id: "dim_causal",
        name: "Comprensión causal",
        justification: "Permite contrastar decisiones y consecuencias observables.",
        verification_priority: 0.9,
        criterion_ids: ["criterion_01"],
        learning_outcome_ids: ["outcome_01"],
        factors: {
          learning_relevance: 0.9,
          centrality: 0.9,
          expected_evidence: 0.9,
          discriminative_potential: 0.8,
          auditability: 0.95,
          short_response_observability: 0.85,
        },
        evidence_variants: [
          {
            variant_id: "variant_tradeoff",
            name: "Decisión con trade-off",
            description: "La entrega explica una decisión y su costo.",
            verification_potential: 0.88,
            evidence_requirement: {
              allowed_modalities: ["PARAGRAPH"],
              min_distinct_units: 1,
              min_extraction_confidence: 0.75,
              min_alignment: 0.65,
              cross_artifact_required: false,
              course_sources_allowed: false,
            },
            supported_operations: [
              {
                cognitive_operation: "EXPLAIN_MECHANISM",
                support_strength: 0.92,
                rationale: "La evidencia conecta decisión y efecto.",
              },
            ],
            question_opportunities: [
              {
                opportunity_template_id: "opportunity_template_01",
                cognitive_operation: "EXPLAIN_MECHANISM",
                focus: "Efecto de la decisión principal",
                observable: "Explica el mecanismo usando la evidencia.",
                difficulty: "MEDIUM",
                target_minutes: 8,
                allowed_anchor_structures: ["SINGLE_FRAGMENT"],
                allowed_response_formats: ["OPEN_SHORT"],
                verification_potential: 0.88,
                minimum_quality: 0.75,
                student_justification_required: false,
              },
            ],
          },
        ],
      },
    ],
  },
  preflight: {
    schema_version: "1.1.0",
    blueprint_id: "blueprint_01",
    blueprint_version: 3,
    policy_constraints_match: true,
    source_coverage_complete: true,
    catalog_size_sufficient: true,
    time_feasible: true,
    format_feasible: true,
    justification_matrix_valid: true,
    catalog_plan_feasible: true,
  },
  review: {
    schema_version: "1.1.0",
    activity_id: "activity_01",
    blueprint_id: "blueprint_01",
    blueprint_version: 3,
    status: "READY",
    approval_recommendation: "REJECT",
    diagnostics: [],
    checks: [
      {
        check_code: "BP_HAS_OPPORTUNITIES",
        category: "COVERAGE",
        status: "FAIL",
        message: "Recomendación histórica sin autoridad vigente.",
        critical: true,
        referenced_ids: ["opportunity_template_01"],
      },
    ],
  },
  issues: [],
};

const guideDraft = {
  purpose: "Observar una explicación causal basada en la entrega.",
  observable_elements: [
    {
      element_id: "element_01",
      description: "Relaciona la decisión con su efecto y su trade-off.",
      evidence_ids: ["evidence_01"],
      source_ids: [],
      required_for_level_2: true,
    },
  ],
  acceptable_alternatives: ["Describe primero el efecto y luego reconstruye la causa."],
  misconceptions: ["Confundir correlación con causalidad."],
  levels: [
    { level: 0, label: "No observable", descriptor: "No usa la evidencia.", observable_element_ids: [] },
    { level: 1, label: "Parcial", descriptor: "Menciona decisión o efecto.", observable_element_ids: ["element_01"] },
    { level: 2, label: "Suficiente", descriptor: "Conecta decisión, efecto y costo.", observable_element_ids: ["element_01"] },
  ],
  cannot_infer: ["Intención personal del estudiante."],
};

export const evaluationGuide: EvaluationGuide = {
  schema_version: "1.1.0",
  guide_id: "guide_01",
  assessment_id: "assessment_01",
  submission_id: "submission_01",
  status: "READY",
  items: [{ question_id: "question_01", guide: guideDraft }],
  diagnostics: [],
  created_at: "2026-07-31T12:00:00Z",
};

const scores = {
  groundedness: 0.96,
  anchor_sufficiency: 0.91,
  criterion_relevance: 0.93,
  answerability: 0.9,
  cognitive_demand: 0.82,
  submission_specificity: 0.95,
  clarity: 0.89,
  accessibility: 0.92,
  discriminative_potential: 0.84,
  guide_observability: 0.94,
};

export const assessmentBundle: AssessmentBundle = {
  etag: '"sha256:assessment-1"',
  assessment_version: 1,
  guide: null,
  guide_status: "NOT_AVAILABLE",
  assessment: {
    schema_version: "1.1.0",
    assessment_id: "assessment_01",
    tenant_id: "tenant_01",
    activity_id: "activity_01",
    submission_id: "submission_01",
    subject_ref: "estudiante_014",
    status: "NEEDS_REVIEW",
    context_mode: "CLOSED",
    assessment_plan_id: "assessment_plan_01",
    question_count: 1,
    questions: [
      {
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
          fragments: [
            {
              evidence_id: "evidence_01",
              display_text: "Se eligió el enfoque A para reducir la latencia.",
              transformation: "LITERAL",
              locator: { kind: "DOCUMENT_PATH", paragraph_index: 3 },
            },
          ],
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
      },
    ],
    coverage: [
      {
        dimension_id: "dim_causal",
        evidence_unit_count: 1,
        available_variant_count: 1,
        available_opportunity_count: 1,
        selected_opportunity_count: 1,
        reused_variant_count: 0,
        diagnostics: [],
      },
    ],
    structured_justification: {
      mode: "NOT_REQUIRED",
      required_question_ids: [],
      limited_evidence_notice_required: false,
    },
    diagnostics: [
      {
        code: "ASSESSMENT_READY_FOR_HUMAN_REVIEW",
        severity: "INFO",
        message: "La evaluación requiere aprobación humana.",
        retryable: false,
      },
    ],
    lineage: {
      assignment_prompt_hashes: [HASH_A],
      rubric_hashes: [],
      submission_hashes: [HASH_B],
      blueprint_id: "blueprint_01",
      blueprint_version: 3,
      parser_versions: { safe: "1.0.0" },
      prompt_versions: { P09: "1.1.0" },
      schema_version: "1.1.0",
      model_snapshots: { mock: "deterministic" },
      policy_hash: HASH_A,
      planner_version: "1.0.0",
      renderer_version: "1.0.0",
    },
    created_at: "2026-07-31T12:00:00Z",
  },
  reviews: [
    {
      question_id: "question_01",
      candidate_id: "candidate_01",
      opportunity_id: "opportunity_01",
      decision: "ACCEPT",
      scores,
      estimated_difficulty: "MEDIUM",
      estimated_minutes: 8,
      confidence: 0.95,
      justifications: ["La pregunta se sostiene en evidencia localizada."],
      evidence_ids: ["evidence_01"],
      source_ids: [],
      diagnostics: [
        {
          code: "QUESTION_GROUNDED",
          severity: "INFO",
          message: "La pregunta se sostiene en evidencia localizada.",
          retryable: false,
        },
      ],
    },
  ],
  evidence: [
    {
      schema_version: "1.1.0",
      evidence_id: "evidence_01",
      tenant_id: "tenant_01",
      submission_id: "submission_01",
      artifact_id: "artifact_01",
      artifact_hash: HASH_B,
      source_role: "SUBMISSION",
      modality: "PARAGRAPH",
      locator: { kind: "DOCUMENT_PATH", paragraph_index: 3 },
      content_text: "Se eligió el enfoque A para reducir la latencia.",
      extraction_confidence: 0.99,
      ocr_used: false,
      relations: [],
      sensitive_labels: [],
      normalized_hash: HASH_A,
    },
  ],
  evidence_receipts: [],
};

export const submission: SubmissionResource = {
  schema_version: "1.1.0",
  submission_id: "submission_01",
  activity_id: "activity_01",
  subject_ref: "estudiante_014",
  status: "NEEDS_REVIEW",
  current_stage: "P09_GUIDE",
  progress: 1,
  active_job_id: "job_01",
  artifact_uploaded: true,
  assessment_id: "assessment_01",
  diagnostics: [],
  updated_at: "2026-07-31T12:00:00Z",
};

export const failedTechnicalJob: JobStatus = {
  schema_version: "1.1.0",
  job_id: "job_01",
  tenant_id: "tenant_01",
  aggregate_id: "submission_01",
  stage: "FINALIZE",
  status: "FAILED",
  progress: 0.97,
  attempt: 2,
  diagnostics: [
    {
      code: "EXPORT_VIEW_FAILED",
      severity: "WARNING",
      message: "Falló una vista derivada; el Assessment canónico sigue revisable.",
      retryable: true,
    },
  ],
};
