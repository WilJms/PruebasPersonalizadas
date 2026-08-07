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

export type ExportKind = Schema<"ExportKindCommand">["kind"];
export type ExportResource = Schema<"ExportResource">;
export type StartedOperation = Schema<"JobStatus">;
