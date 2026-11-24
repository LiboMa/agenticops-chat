import type { ComponentType } from "react";
import type { BriefKind, ItemKind } from "../../lib/briefKind";
import { AcceptBrief } from "./AcceptBrief";
import { ApproveBrief } from "./ApproveBrief";
import type { BriefProps } from "./briefContext";
import { ChangeAcceptBrief, ChangeApproveBrief, ClarifyBrief, StartReviewBrief } from "./ChangeBriefs";
import { ConfirmBrief } from "./ConfirmBrief";
import { FailedBrief } from "./FailedBrief";
import { GenerateBrief } from "./GenerateBrief";
import { ChangeNotStartedBrief, NotStartedBrief } from "./NotStartedBrief";
import { ReplanBrief } from "./ReplanBrief";
import { RerunBrief } from "./RerunBrief";
import { ResolveBrief } from "./ResolveBrief";

/** The page of each kind of waiting item, for an issue and for a change. Every row of the shared table
 *  (tests/fixtures/attention_brief_kinds.json) has one — a test says so; a row this client does not know gets the
 *  generic brief. */
export const BRIEFS: Record<BriefKind, Partial<Record<ItemKind, ComponentType<BriefProps>>>> = {
  approve: { issue: ApproveBrief, change: ChangeApproveBrief },
  accept: { issue: AcceptBrief, change: ChangeAcceptBrief },
  resolve: { issue: ResolveBrief },
  confirm: { issue: ConfirmBrief },
  rerun: { issue: RerunBrief },
  generate: { issue: GenerateBrief },
  replan: { issue: ReplanBrief },
  failed: { issue: FailedBrief },
  not_started: { issue: NotStartedBrief, change: ChangeNotStartedBrief },
  start_review: { change: StartReviewBrief },
  clarify: { change: ClarifyBrief },
};
