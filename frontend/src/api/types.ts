/** Public client aliases generated from the checked-in Stage 1 OpenAPI schema. */

import type { components } from "./generated";

type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type AssessmentModality = NonNullable<
  Schema<"ActivityCreateCommand">["assessment_modality"]
>;
export type ResponseFormat = Schema<"ActivityCreateCommand">["allowed_response_formats"][number];
export type StructuredJustificationMode = NonNullable<
  Schema<"ActivityCreateCommand">["structured_justification_mode"]
>;
export type TechnicalJobState = Schema<"JobStatus">["status"];
export type SubmissionDomainState = Schema<"SubmissionResource">["status"];

export type Diagnostic = Schema<"Diagnostic">;
export type Session = Schema<"SessionResource">;
export type ActivityCreateInput = Schema<"ActivityCreateCommand">;
export type ActivityUpdateInput = Schema<"ActivityUpdateCommand">;
export type ActivityResource = Schema<"ActivityResource">;
export type ActivityJourney = Schema<"ActivityJourney">;
export type ArtifactResource = Schema<"ArtifactResource">;
export type UploadSession = Schema<"UploadResource">;

export type BlueprintOpportunity = Schema<"QuestionOpportunityTemplate">;
export type SupportedOperation = Schema<"SupportedOperation">;
export type BlueprintVariant = Schema<"EvidenceVariant">;
export type BlueprintDimension = Schema<"BlueprintDimension">;
export type AssessmentBlueprint = Schema<"AssessmentBlueprint">;
export type BlueprintPreflight = Schema<"BlueprintReviewPreflight">;
export type BlueprintReviewCheck = Schema<"BlueprintReviewCheck">;
export type BlueprintView = Schema<"BlueprintEnvelope">;

export type AmbiguityDecisionOption = Schema<"DecisionOption">;
export type AmbiguityIssue = Schema<"AmbiguityIssue">;
export type AmbiguityReport = Schema<"AmbiguityReport">;
export type PolicyDecision = Schema<"PolicyDecision">;
export type AmbiguityView = Schema<"AmbiguityEnvelope">;

export type JobStatus = Schema<"JobStatus">;
export type SubmissionResource = Schema<"SubmissionResource">;
export type SourceLocator = Schema<"EvidenceResource">["locator"];
export type EvidenceUnit = Schema<"EvidenceResource">;
export type AnchorFragment = Schema<"AnchorFragment">;
export type SelectedQuestion = Schema<"SelectedQuestion">;
export type QuestionScores = Schema<"QuestionScores">;
export type QuestionReview = Schema<"QuestionReviewResource">;
export type Assessment = Schema<"Assessment">;
export type AssessmentBundle = Schema<"AssessmentEnvelope">;
export type GuideItem = Schema<"EvaluationGuideItem">;
export type EvaluationGuide = Schema<"EvaluationGuide">;
export type EvidenceReceipt = Schema<"EvidenceReceipt">;
export type EvidenceVerification = Schema<"EvidenceVerifyResource">;
export type CostEstimate = Schema<"CostEstimate">;

/** Stage 2 keeps exports as derived views of the same approved canonical objects. */
export type ExportKind = Schema<"ExportKind">;
export type ExportResource = Schema<"ExportResource">;
export type StartedOperation = Schema<"JobStatus">;

export type Stage2Submission = SubmissionResource & {
  assessment_version?: number | null;
  job_status?: TechnicalJobState | null;
};

export type SubmissionBatchResult = Schema<"SubmissionBatchEnvelope">;
export type QuestionReviewAction = Schema<"QuestionReviewActionType">;
export type QuestionReviewActionInput = Schema<"QuestionReviewActionCommand">;
export type QuestionReviewActionEvent = Schema<"QuestionReviewAction">;
export type Lineage = Schema<"Lineage">;
export type QuestionReviewActionRecord = Schema<"QuestionReviewActionRecord">;
export type CoverageSummaryItem = Schema<"CoverageItem">;
export type CoverageTraceItem = Schema<"CoverageTraceItem">;
export type CoverageReport = Schema<"CoverageReport">;
export type ExperimentMetrics = Schema<"ExperimentMetrics">;
export type FeedbackTarget = Schema<"FeedbackTargetType">;
export type FeedbackRating = Schema<"FeedbackRating">;
export type FeedbackCategory = Schema<"FeedbackCategory">;
export type FeedbackInput = Schema<"FeedbackCommand">;
export type FeedbackEvent = Schema<"FeedbackEvent">;
export type ExportArtifact = Schema<"ExportArtifact">;
export type ExportRecord = Schema<"ExportRecord">;
export type ExportDownloadResource = Schema<"ExportDownloadResource">;
export type ExportCreateResult = Schema<"ExportCreateEnvelope">;
export type StageRunView = Schema<"StageRun">;
export type FailureClass = Schema<"FailureClass">;
export type JobControlRecord = Schema<"JobControlRecord">;
export type JobControlView = Schema<"JobControlEnvelope">;
export type BulkApprovalTarget = Schema<"AssessmentVersionRef">;
export type BulkApprovalRecord = Schema<"BulkApprovalRecord">;

export const BULK_APPROVAL_CONFIRMATION =
  "CONFIRM_BULK_APPROVAL_OF_ALL_ELIGIBLE_SELECTED_ASSESSMENTS" as const;
