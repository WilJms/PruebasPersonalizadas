import type {
  AssessmentBundle,
  AmbiguityView,
  BlueprintView,
  EvaluationGuide,
  JobStatus,
  SubmissionResource,
} from "../api/types";

export const ambiguityView: AmbiguityView = {
  report: {
    schema_version: "1.1",
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
          {
            option_id: "option_keep",
            label: "Mantener alcance",
            consequence: "Conserva el alcance explícito de la consigna.",
          },
          {
            option_id: "option_narrow",
            label: "Acotar alcance",
            consequence: "Limita la verificación a la evidencia más directa.",
          },
        ],
        recommended_option_id: "option_keep",
        blocking: true,
      },
    ],
  },
  decisions: [],
};

export const blueprintView: BlueprintView = {
  etag: 'W/"blueprint-3"',
  blueprint: {
    schema_version: "1.1",
    blueprint_id: "bp_01",
    blueprint_version: 3,
    activity_id: "activity_01",
    status: "NEEDS_REVIEW",
    context_mode: "CLOSED",
    assessment_constraints: {
      question_count: 1,
      target_total_minutes: 8,
      allowed_response_formats: ["OPEN_SHORT"],
    },
    dimensions: [
      {
        dimension_id: "dim_causal",
        name: "Comprensión causal",
        justification: "Permite contrastar decisiones y consecuencias observables.",
        verification_priority: 0.9,
        criterion_ids: ["criterion_01"],
        evidence_variants: [
          {
            variant_id: "variant_tradeoff",
            name: "Decisión con trade-off",
            description: "La entrega explica una decisión y su costo.",
            verification_potential: 0.88,
            supported_operations: [
              {
                cognitive_operation: "EXPLAIN_CAUSALLY",
                support_strength: 0.92,
                rationale: "La evidencia conecta decisión y efecto.",
              },
            ],
            question_opportunities: [
              {
                opportunity_template_id: "opp_01",
                cognitive_operation: "EXPLAIN_CAUSALLY",
                focus: "Efecto de la decisión principal",
                observable: "Explica la cadena causal usando la evidencia.",
                difficulty: "MEDIUM",
                target_minutes: 8,
                allowed_response_formats: ["OPEN_SHORT"],
              },
            ],
          },
        ],
      },
    ],
  },
  review: {
    status: "READY",
    approval_recommendation: "APPROVE",
    checks: [
      {
        check_code: "BP_HAS_OPPORTUNITIES",
        category: "COVERAGE",
        status: "PASS",
        message: "Existe una oportunidad verificable.",
        critical: true,
      },
    ],
  },
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
  etag: 'W/"assessment-1"',
  assessment_version: 1,
  assessment: {
    assessment_id: "assessment_01",
    activity_id: "activity_01",
    submission_id: "submission_01",
    subject_ref: "estudiante_014",
    status: "NEEDS_REVIEW",
    question_count: 1,
    questions: [
      {
        question_id: "question_01",
        dimension_id: "dim_causal",
        variant_id: "variant_tradeoff",
        cognitive_operation: "EXPLAIN_CAUSALLY",
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
              display_text: "Se eligió el enfoque A para reducir la latencia, aceptando menor detalle.",
              transformation: "VERBATIM",
              locator: { kind: "PDF_TEXT", page: 3, block_index: 2 },
            },
          ],
          self_containment_score: 0.92,
          answer_leakage_risk: 0.08,
        },
        evidence_ids: ["evidence_01"],
        planning_score: 0.91,
      },
    ],
    diagnostics: [
      {
        code: "ASSESSMENT_READY_FOR_HUMAN_REVIEW",
        severity: "INFO",
        message: "La evaluación requiere aprobación humana.",
      },
    ],
  },
  reviews: [
    {
      question_id: "question_01",
      opportunity_id: "opp_01",
      decision: "ACCEPT",
      scores,
      diagnostics: [
        {
          code: "QUESTION_GROUNDED",
          severity: "INFO",
          message: "La pregunta se sostiene en evidencia localizada.",
        },
      ],
    },
  ],
  evidence: [
    {
      evidence_id: "evidence_01",
      artifact_id: "artifact_01",
      artifact_hash: "sha256:abc",
      modality: "PDF_TEXT",
      locator: { kind: "PDF_TEXT", page: 3, block_index: 2 },
      content_text: "Se eligió el enfoque A para reducir la latencia.",
      extraction_confidence: 0.99,
      view_url: "https://example.test/private/evidence_01",
    },
  ],
};

export const evaluationGuide: EvaluationGuide = {
  guide_id: "guide_01",
  assessment_id: "assessment_01",
  submission_id: "submission_01",
  status: "READY",
  items: [
    {
      question_id: "question_01",
      guide: {
        purpose: "Observar una explicación causal basada en la entrega.",
        observable_elements: [
          {
            element_id: "element_01",
            description: "Relaciona la decisión con su efecto y su trade-off.",
            evidence_ids: ["evidence_01"],
            required_for_level_2: true,
          },
        ],
        acceptable_alternatives: ["Describe primero el efecto y luego reconstruye la causa."],
        misconceptions: ["Confundir correlación con causalidad."],
        levels: [
          { level: 0, label: "No observable", descriptor: "No usa la evidencia." },
          { level: 1, label: "Parcial", descriptor: "Menciona decisión o efecto." },
          { level: 2, label: "Suficiente", descriptor: "Conecta decisión, efecto y costo." },
        ],
        cannot_infer: ["Intención personal del estudiante."],
      },
    },
  ],
};

export const submission: SubmissionResource = {
  submission_id: "submission_01",
  activity_id: "activity_01",
  subject_ref: "estudiante_014",
  status: "NEEDS_REVIEW",
  current_stage: "P09_GUIDE",
  progress: 1,
  active_job_id: "job_01",
  assessment_id: "assessment_01",
};

export const failedTechnicalJob: JobStatus = {
  job_id: "job_01",
  stage: "FINALIZE",
  status: "FAILED",
  progress: 0.97,
  attempt: 2,
  diagnostics: [
    {
      code: "EXPORT_VIEW_FAILED",
      severity: "WARNING",
      message: "Falló una vista derivada; el assessment canónico sigue revisable.",
      retryable: true,
    },
  ],
};
