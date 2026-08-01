export type AssessmentModality = "WRITTEN" | "ORAL" | "MIXED";

export type ResponseFormat =
  | "OPEN_SHORT"
  | "STRUCTURED_BULLETS"
  | "CHOICE"
  | "ANNOTATION_OR_DIAGRAM"
  | "ORAL_EQUIVALENT";

export type StructuredJustificationMode = "NOT_REQUIRED" | "SELECTED" | "ALL";

export type TechnicalJobState =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "NEEDS_REVIEW";

export type SubmissionDomainState =
  | "UPLOADED"
  | "VALIDATING"
  | "PARSING"
  | "EVIDENCE_READY"
  | "MAPPING_OPPORTUNITIES"
  | "PLANNING"
  | "GENERATING"
  | "VALIDATING_QUESTIONS"
  | "GUIDE_READY"
  | "NEEDS_REVIEW"
  | "APPROVED"
  | "INSUFFICIENT_RELEVANT_EVIDENCE"
  | "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES"
  | "EVIDENCE_MAPPING_UNCERTAIN"
  | "ASSESSMENT_PLAN_INFEASIBLE"
  | "TECHNICAL_FAILURE"
  | "REJECTED_SECURITY"
  | "CANCELLED";

export interface Diagnostic {
  code: string;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  message: string;
  evidence_ids?: string[];
  retryable?: boolean;
}

export interface Session {
  user_id: string;
  email: string;
  display_name?: string;
  workspace_id: string;
  workspace_name: string;
  roles: string[];
}

export interface ActivityCreateInput {
  title: string;
  output_language: string;
  assessment_modality: AssessmentModality;
  question_count: number;
  target_total_minutes: number;
  allowed_response_formats: ResponseFormat[];
  allowed_artifact_media_types: string[];
  structured_justification_mode: StructuredJustificationMode;
  context_mode: "CLOSED";
}

export interface ActivityResource extends ActivityCreateInput {
  activity_id: string;
  tenant_id?: string;
  status: string;
  latest_blueprint_version?: number;
  approved_blueprint_version?: number;
}

export interface ArtifactResource {
  artifact_id: string;
  filename: string;
  media_type: string;
  byte_size: number;
  sha256: string;
  role?: string;
}

export interface UploadSession {
  artifact_id: string;
  upload_url: string;
  upload_headers?: Record<string, string>;
  expires_at?: string;
}

export interface BlueprintOpportunity {
  opportunity_template_id: string;
  cognitive_operation: string;
  focus: string;
  observable: string;
  difficulty: string;
  target_minutes: number;
  allowed_response_formats: string[];
  student_justification_required?: boolean;
}

export interface SupportedOperation {
  cognitive_operation: string;
  support_strength: number;
  rationale: string;
}

export interface BlueprintVariant {
  variant_id: string;
  name: string;
  description: string;
  verification_potential: number;
  supported_operations: SupportedOperation[];
  question_opportunities: BlueprintOpportunity[];
}

export interface BlueprintDimension {
  dimension_id: string;
  name: string;
  justification: string;
  verification_priority: number;
  criterion_ids: string[];
  evidence_variants: BlueprintVariant[];
}

export interface AssessmentBlueprint {
  schema_version: string;
  blueprint_id: string;
  blueprint_version: number;
  activity_id: string;
  status: string;
  context_mode: "CLOSED" | "COURSE_ENRICHED";
  dimensions: BlueprintDimension[];
  assessment_constraints: {
    question_count: number;
    target_total_minutes: number;
    allowed_response_formats: string[];
  };
  diagnostics?: Diagnostic[];
  approved_by?: string | null;
  approved_at?: string | null;
}

export interface BlueprintReviewCheck {
  check_code: string;
  category: string;
  status: "PASS" | "WARN" | "FAIL";
  message: string;
  critical: boolean;
}

export interface BlueprintView {
  blueprint: AssessmentBlueprint;
  etag: string;
  review?: {
    status: string;
    approval_recommendation?: string | null;
    checks: BlueprintReviewCheck[];
    diagnostics?: Diagnostic[];
  };
  issues?: Diagnostic[];
}

export interface AmbiguityDecisionOption {
  option_id: string;
  label: string;
  consequence: string;
}

export interface AmbiguityIssue {
  issue_id: string;
  issue_code: string;
  severity: Diagnostic["severity"];
  evidence_ids: string[];
  explanation: string;
  options: AmbiguityDecisionOption[];
  recommended_option_id: string;
  blocking: boolean;
}

export interface AmbiguityReport {
  schema_version: string;
  activity_id: string;
  issues: AmbiguityIssue[];
  blocked: boolean;
}

export interface PolicyDecision {
  schema_version: string;
  decision_id: string;
  issue_id: string;
  selected_option_id: string;
  decided_by: string;
  decided_at: string;
  note?: string | null;
}

export interface AmbiguityView {
  report: AmbiguityReport;
  decisions: PolicyDecision[];
}

export interface JobStatus {
  job_id: string;
  stage: string;
  status: TechnicalJobState;
  progress: number;
  attempt: number;
  diagnostics?: Diagnostic[];
  started_at?: string | null;
  finished_at?: string | null;
}

export interface SubmissionResource {
  submission_id: string;
  activity_id: string;
  subject_ref: string;
  status: SubmissionDomainState;
  current_stage?: string | null;
  progress: number;
  active_job_id?: string | null;
  assessment_id?: string | null;
  diagnostics?: Diagnostic[];
}

export interface SourceLocator {
  kind: string;
  [key: string]: string | number | boolean | null | string[] | number[] | undefined;
}

export interface EvidenceUnit {
  evidence_id: string;
  artifact_id: string;
  artifact_hash: string;
  modality: string;
  locator: SourceLocator;
  content_text?: string | null;
  extraction_confidence: number;
  view_url?: string | null;
}

export interface AnchorFragment {
  evidence_id: string;
  display_text?: string | null;
  transformation: string;
  locator: SourceLocator;
}

export interface SelectedQuestion {
  question_id: string;
  dimension_id: string;
  variant_id: string;
  cognitive_operation: string;
  response_format: string;
  difficulty: string;
  estimated_minutes: number;
  question_text: string;
  anchor: {
    anchor_id: string;
    structure: string;
    fragments: AnchorFragment[];
    self_containment_score: number;
    answer_leakage_risk: number;
  };
  evidence_ids: string[];
  planning_score: number;
}

export interface QuestionScores {
  groundedness: number;
  anchor_sufficiency: number;
  criterion_relevance: number;
  answerability: number;
  cognitive_demand: number;
  submission_specificity: number;
  clarity: number;
  accessibility: number;
  discriminative_potential: number;
  guide_observability: number;
}

export interface QuestionReview {
  question_id?: string;
  candidate_id?: string;
  opportunity_id?: string;
  decision: "ACCEPT" | "REJECT" | "ESCALATE";
  scores: QuestionScores;
  critical_failure_codes?: string[];
  diagnostics?: Diagnostic[];
}

export interface Assessment {
  assessment_id: string;
  activity_id: string;
  submission_id: string;
  subject_ref: string;
  status: string;
  question_count: number;
  questions: SelectedQuestion[];
  diagnostics?: Diagnostic[];
  approved_by?: string | null;
  approved_at?: string | null;
}

export interface AssessmentBundle {
  assessment: Assessment;
  reviews: QuestionReview[];
  evidence: EvidenceUnit[];
  etag: string;
  assessment_version?: number;
}

export interface GuideItem {
  question_id: string;
  guide: {
    purpose: string;
    observable_elements: Array<{
      element_id: string;
      description: string;
      evidence_ids: string[];
      required_for_level_2: boolean;
    }>;
    acceptable_alternatives: string[];
    misconceptions: string[];
    levels: Array<{
      level: number;
      label: string;
      descriptor: string;
    }>;
    cannot_infer: string[];
  };
}

export interface EvaluationGuide {
  guide_id: string;
  assessment_id: string;
  submission_id: string;
  status: string;
  items: GuideItem[];
  diagnostics?: Diagnostic[];
}

export type ExportKind = "ASSESSMENT_PDF" | "GUIDE_PDF" | "CANONICAL_JSON";

export interface ExportResource {
  export_id: string;
  kind: ExportKind;
  status: "QUEUED" | "READY" | "FAILED";
  download_url?: string | null;
  expires_at?: string | null;
}

export interface StartedOperation {
  job_id: string;
  blueprint_version?: number;
  submission_id?: string;
}
