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

// Each kind of line gets a colour and a word, so the colour is never the only cue.
type Kind = "note" | "ai" | "status";

const KIND: Record<Kind, { label: string; row: string; badge: string }> = {
  note: { label: "Details", row: "border-sky-400 bg-sky-50", badge: "bg-sky-100 text-sky-800" },
  ai: { label: "AI suggestion", row: "border-violet-400 bg-violet-50", badge: "bg-violet-100 text-violet-800" },
  status: { label: "Status", row: "border-slate-300 bg-slate-50", badge: "bg-slate-200 text-slate-700" },
};

const KIND_OF: Record<AuditEvent["event_type"], Kind> = {
  field_edit: "note",
  suggestion_decision: "ai",
  suggestions_stale: "ai",
  status_change: "status",
  created: "status",
};

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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label className="text-muted-foreground">History</Label>
        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(KIND) as Kind[]).map((k) => (
            <span key={k} className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${KIND[k].badge}`}>
              {KIND[k].label}
            </span>
          ))}
        </div>
      </div>
      {failed ? (
        <p className="mt-1 text-sm text-muted-foreground">Couldn't load the history.</p>
      ) : events === null ? null : (
        <ol className="mt-2 space-y-1.5 text-sm">
          {events.map((e) => {
            const kind = KIND[KIND_OF[e.event_type] ?? "status"];
            return (
              <li
                key={e.id}
                className={`flex flex-col gap-0.5 rounded-r-md border-l-4 px-3 py-1.5 sm:flex-row sm:justify-between sm:gap-3 ${kind.row}`}
              >
                <span className="break-words">
                  <span className={`mr-2 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase ${kind.badge}`}>
                    {kind.label}
                  </span>
                  {describe(e)}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {e.adjuster_name ? `${e.adjuster_name}, ` : ""}
                  {parseUtc(e.created_at).toLocaleString()}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
