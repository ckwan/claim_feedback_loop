import { useEffect, useState } from "react";
import { api, type AuditEvent, type Claim } from "@/lib/api";
import { parseUtc } from "@/lib/time";
import { Label } from "@/components/ui/label";

const FIELD_LABEL: Record<string, string> = {
  claimant_name: "Claimant",
  amount: "Amount",
  history_notes: "History notes",
};

const short = (v: string | null, max = 60) => (v === null ? "none" : v.length > max ? `${v.slice(0, max)}…` : v);

function describe(e: AuditEvent): string {
  switch (e.event_type) {
    case "created":
      return `Claim created as ${e.new_value}`;
    case "field_edit":
      return `${FIELD_LABEL[e.field ?? ""] ?? e.field}: ${short(e.old_value)} → ${short(e.new_value)}`;
    case "status_change":
      return `Status: ${e.old_value} → ${e.new_value}`;
    case "suggestion_decision":
      return `AI suggestion ${e.field}: AI said ${e.old_value}, decided ${e.new_value}${e.detail ? ` (${short(e.detail, 80)})` : ""}`;
    case "suggestions_stale":
      return `AI suggestions ${e.new_value}`;
    default:
      return e.event_type;
  }
}

/** Everything that happened to the claim, newest first. Reloads when the claim changes. */
export function ClaimHistory({ orgId, claim }: { orgId: string; claim: Claim }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    api
      .getClaimHistory(orgId, claim.id)
      .then((list) => current && (setEvents(list), setFailed(false)))
      .catch(() => current && setFailed(true));
    return () => {
      current = false;
    };
  }, [orgId, claim.id, claim.updated_at]);

  return (
    <div>
      <Label className="text-muted-foreground">History</Label>
      {failed ? (
        <p className="mt-1 text-sm text-muted-foreground">Couldn't load the history.</p>
      ) : events === null ? null : (
        <ol className="mt-1 space-y-1 text-sm">
          {events.map((e) => (
            <li key={e.id} className="flex flex-col gap-0.5 sm:flex-row sm:justify-between sm:gap-3">
              <span className="break-words">{describe(e)}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {e.adjuster_name ? `${e.adjuster_name}, ` : ""}
                {parseUtc(e.created_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
