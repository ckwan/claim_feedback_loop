import { useState } from "react";
import { api, type Claim } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Check, X, Loader2 } from "lucide-react";

type Decision = "approved" | "denied";

// api.ts throws `409 Conflict: {"detail":"..."}`. Show only the detail.
export function detailOf(e: unknown): string {
  const message = (e as Error).message;
  try {
    return JSON.parse(message.slice(message.indexOf("{"))).detail ?? message;
  } catch {
    return message;
  }
}

/**
 * Approve / Deny for a claim that is under review. Both are final, so a click
 * only asks for confirmation; the PATCH happens on the second click.
 */
export function ReviewActions({
  orgId,
  adjusterId,
  claim,
  onChanged,
}: {
  orgId: string;
  adjusterId?: string | null;
  claim: Claim;
  onChanged: () => void;
}) {
  const [confirming, setConfirming] = useState<Decision | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (claim.status !== "under_review") return null;

  async function apply(decision: Decision) {
    setBusy(true);
    setError(null);
    try {
      await api.updateClaimStatus(orgId, claim.id, decision, adjusterId);
      setConfirming(null);
      onChanged();
    } catch (e) {
      setError(detailOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      {confirming === null ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" className="gap-2" onClick={() => setConfirming("approved")}>
            <Check className="h-4 w-4" />
            Approve
          </Button>
          <Button size="sm" variant="destructive" className="gap-2" onClick={() => setConfirming("denied")}>
            <X className="h-4 w-4" />
            Deny
          </Button>
        </div>
      ) : (
        <div className="space-y-2 rounded-md border bg-muted/40 p-3">
          <p className="text-sm">
            {confirming === "approved" ? "Approve" : "Deny"} this claim? This is final and can't be undone.
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={confirming === "denied" ? "destructive" : "default"}
              className="gap-2"
              disabled={busy}
              onClick={() => apply(confirming)}
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              Confirm {confirming === "approved" ? "approval" : "denial"}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
