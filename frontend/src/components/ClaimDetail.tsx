import { useState } from "react";
import { api, type Claim, type ClaimStatus, type HistorySummary, type Suggestion } from "@/lib/api";
import { InvestigationPanel } from "@/components/InvestigationPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/StatusBadge";
import { Sparkles, ThumbsUp, ThumbsDown, BookOpen, Loader2 } from "lucide-react";

interface Props {
  orgId: string;
  adjusterId: string | null;
  claim: Claim;
  onChanged: () => void;
}

type Phase = "idle" | "loading-suggestion" | "awaiting-decision" | "overriding" | "submitting" | "done";

// Mirrors VALID_TRANSITIONS in backend/app/models.py. Duplicated here (not
// fetched from the API) so the UI can disable/hide illegal choices before
// a request round-trip — the backend is still the source of truth and
// re-validates on every POST /suggestions/{id}/feedback, so a mismatch
// here is a UX annoyance, not a correctness bug.
const VALID_TRANSITIONS: Record<ClaimStatus, ClaimStatus[]> = {
  open: ["under_review"],
  under_review: ["approved", "denied"],
  approved: [],
  denied: [],
};

const STATUS_LABEL: Record<ClaimStatus, string> = {
  open: "Send to review",
  under_review: "Under review",
  approved: "Approve",
  denied: "Deny",
};

export function ClaimDetail({ orgId, adjusterId, claim, onChanged }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [summary, setSummary] = useState<HistorySummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGetSuggestion() {
    setError(null);
    setPhase("loading-suggestion");
    try {
      const s = await api.requestSuggestion(orgId, claim.id);
      setSuggestion(s);
      setPhase("awaiting-decision");
    } catch (e) {
      setError((e as Error).message);
      setPhase("idle");
    }
  }

  async function handleAccept() {
    if (!suggestion || !adjusterId) return;
    setPhase("submitting");
    setError(null);
    try {
      await api.submitFeedback(orgId, suggestion.id, {
        adjuster_id: adjusterId,
        action_taken: "accepted",
        final_action: suggestion.suggested_action,
      });
      setPhase("done");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
      setPhase("awaiting-decision");
    }
  }

  async function handleOverrideSubmit(finalAction: string) {
    if (!suggestion || !adjusterId || !overrideReason.trim()) return;
    setPhase("submitting");
    setError(null);
    try {
      await api.submitFeedback(orgId, suggestion.id, {
        adjuster_id: adjusterId,
        action_taken: "overridden",
        final_action: finalAction,
        override_reason: overrideReason.trim(),
      });
      setPhase("done");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
      setPhase("overriding");
    }
  }

  async function handleHistorySummary() {
    setSummaryLoading(true);
    setError(null);
    try {
      const res = await api.getHistorySummary(orgId, claim.id);
      setSummary(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSummaryLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{claim.claimant_name}</CardTitle>
          <StatusBadge status={claim.status} />
        </div>
        <CardDescription>
          ${claim.amount.toLocaleString()} &middot; claim {claim.id.slice(0, 8)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <Label className="text-muted-foreground">History notes</Label>
          <p className="mt-1 text-sm">{claim.history_notes || "—"}</p>
        </div>

        <Separator />

        {phase === "idle" && (
          <Button onClick={handleGetSuggestion} className="gap-2">
            <Sparkles className="h-4 w-4" />
            Get AI suggestion
          </Button>
        )}

        {phase === "loading-suggestion" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Generating suggestion…
          </div>
        )}

        {suggestion && phase !== "loading-suggestion" && (
          <div className="rounded-md border bg-muted/40 p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">AI suggests:</span>
              <Badge variant="outline">{suggestion.suggested_action}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">{suggestion.rationale}</p>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>Confidence: {(suggestion.confidence * 100).toFixed(0)}%</span>
              <span>&middot;</span>
              <span>{suggestion.model_version}</span>
            </div>
          </div>
        )}

        {phase === "awaiting-decision" && adjusterId && suggestion?.suggested_action === "no_action" && (
          <p className="text-sm text-muted-foreground">
            This claim is already {claim.status} — there's nothing left to
            accept or override.
          </p>
        )}

        {phase === "awaiting-decision" && adjusterId && suggestion?.suggested_action !== "no_action" && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={handleAccept} variant="default" className="gap-2">
              <ThumbsUp className="h-4 w-4" />
              Accept suggestion
            </Button>
            {VALID_TRANSITIONS[claim.status].filter((s) => s !== suggestion?.suggested_action).length > 0 && (
              <Button onClick={() => setPhase("overriding")} variant="outline" className="gap-2">
                <ThumbsDown className="h-4 w-4" />
                Override
              </Button>
            )}
          </div>
        )}

        {phase === "awaiting-decision" && !adjusterId && (
          <p className="text-sm text-amber-700">
            Select an adjuster above before you can accept or override a suggestion.
          </p>
        )}

        {phase === "overriding" && (
          <div className="space-y-3">
            <div>
              <Label htmlFor="override-reason">Why are you overriding this?</Label>
              <Textarea
                id="override-reason"
                className="mt-1"
                placeholder="e.g. Claimant has a prior SIU flag not reflected in the notes…"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                This reason is stored and reused as context for the model's next
                suggestion on this org's claims — it's what actually closes the
                feedback loop, not just a log entry.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {VALID_TRANSITIONS[claim.status]
                .filter((status) => status !== suggestion?.suggested_action)
                .map((status) => (
                  <Button
                    key={status}
                    size="sm"
                    variant="secondary"
                    disabled={!overrideReason.trim()}
                    onClick={() => handleOverrideSubmit(status)}
                  >
                    {STATUS_LABEL[status]} instead
                  </Button>
                ))}
              <Button size="sm" variant="ghost" onClick={() => setPhase("awaiting-decision")}>
                Cancel
              </Button>
            </div>
            {VALID_TRANSITIONS[claim.status].filter((s) => s !== suggestion?.suggested_action).length === 0 && (
              <p className="text-xs text-muted-foreground">
                No alternative action is available from this claim's current status
                ({claim.status}) — the only valid next step is what the AI already
                suggested.
              </p>
            )}
          </div>
        )}

        {phase === "submitting" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Recording your decision…
          </div>
        )}

        {phase === "done" && (
          <p className="text-sm text-emerald-700">
            Decision recorded. It will be used as context on this org's next AI suggestion.
          </p>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-2 border-t pt-4">
        <Button
          variant="ghost"
          size="sm"
          className="gap-2 self-start"
          onClick={handleHistorySummary}
          disabled={summaryLoading}
        >
          {summaryLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <BookOpen className="h-4 w-4" />
          )}
          View similar-claims summary (RAG)
        </Button>
        {summary && (
          <div className="space-y-2 rounded-md bg-muted/40 p-3 text-sm">
            <p className="text-muted-foreground">{summary.summary}</p>
            {summary.sources.length > 0 && (
              <>
                {!summary.grounded && (
                  <p className="text-xs text-amber-700">
                    This summary cites no source, so treat it with caution.
                  </p>
                )}
                <ol className="space-y-1 border-t pt-2 text-xs text-muted-foreground">
                  {summary.sources.map((src, i) => (
                    <li key={src.claim_id}>
                      <span className="font-medium">[{i + 1}]</span> {src.claimant_name}: {src.snippet}
                    </li>
                  ))}
                </ol>
              </>
            )}
          </div>
        )}
        <InvestigationPanel key={claim.id} orgId={orgId} claimId={claim.id} />
      </CardFooter>
    </Card>
  );
}
