import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ClaimStats, type ClaimStatus, type QueueItem } from "@/lib/api";
import { VALID_TRANSITIONS } from "@/components/ClaimDetail";
import { DecisionDialog } from "@/components/DecisionDialog";
import { detailOf } from "@/components/ReviewActions";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Loader2 } from "lucide-react";

type Tab = "all" | ClaimStatus;

const TABS: { value: Tab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "under_review", label: "Under review" },
  { value: "approved", label: "Approved" },
  { value: "denied", label: "Denied" },
];

const EMPTY: Record<Tab, string> = {
  all: "No claims yet.",
  open: "No open claims.",
  under_review: "Nothing is waiting for review.",
  approved: "No approved claims yet.",
  denied: "No denied claims yet.",
};

// What the button for moving *to* a status is called.
const ACTION_LABEL: Partial<Record<ClaimStatus, string>> = {
  under_review: "Start review",
  approved: "Approve",
  denied: "Deny",
};

const PAGE_SIZE = 100; // the backend caps GET /claims/queue at 100

const countFor = (stats: ClaimStats | null, tab: Tab) =>
  stats ? (tab === "all" ? stats.total : stats.by_status[tab]) : null;

// The API sends UTC timestamps without a zone, which the browser would read as local time.
function ageInDays(createdAt: string): number {
  const utc = /Z|[+-]\d\d:?\d\d$/.test(createdAt) ? createdAt : `${createdAt}Z`;
  return Math.max(0, Math.floor((Date.now() - new Date(utc).getTime()) / 86_400_000));
}

// What choosing `target` means for this claim. An unanswered AI suggestion is answered
// by the same click: accepted when it matches, overridden (with a reason) when it doesn't.
function plan(item: QueueItem, target: ClaimStatus) {
  const pending = item.latest_suggestion && !item.latest_suggestion.has_feedback ? item.latest_suggestion : null;
  return {
    pending,
    override: pending !== null && pending.suggested_action !== target,
    final: VALID_TRANSITIONS[target].length === 0,
  };
}

interface Props {
  orgId: string;
  adjusterId: string | null;
  stats: ClaimStats | null;
  onOpen: (claimId: string) => void;
  onChanged: () => void; // refreshes the claim list and the stats cards
}

export function ReviewQueue({ orgId, adjusterId, stats, onOpen, onChanged }: Props) {
  const [tab, setTab] = useState<Tab>("under_review");
  const [rows, setRows] = useState<QueueItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<{ item: QueueItem; target: ClaimStatus } | null>(null);
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null);
  const latestRequest = useRef(0);

  const load = useCallback(async () => {
    const request = ++latestRequest.current;
    try {
      const list = await api.getQueue(orgId, tab === "all" ? undefined : tab);
      if (request === latestRequest.current) {
        setRows(list);
        setLoadError(null);
      }
    } catch (e) {
      if (request === latestRequest.current) setLoadError(detailOf(e));
    }
  }, [orgId, tab]);

  useEffect(() => {
    setRows(null);
    load();
  }, [load]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(timer);
  }, [toast]);

  async function perform(item: QueueItem, target: ClaimStatus, note: string) {
    setDialog(null);
    setBusy((b) => new Set(b).add(item.id));
    try {
      const { pending, override } = plan(item, target);
      if (pending) {
        // The feedback endpoint applies the status change itself, through the same
        // transition check as PATCH, so PATCH is not called as well.
        if (!adjusterId) throw new Error("Select an adjuster before answering a suggestion.");
        await api.submitFeedback(orgId, pending.id, {
          adjuster_id: adjusterId,
          action_taken: override ? "overridden" : "accepted",
          final_action: target,
          override_reason: override ? note : undefined,
        });
      } else {
        await api.updateClaimStatus(orgId, item.id, target);
      }
      setToast({ message: `${item.claimant_name}: ${ACTION_LABEL[target]} done.`, error: false });
    } catch (e) {
      setToast({ message: detailOf(e), error: true });
    } finally {
      setBusy((b) => {
        const next = new Set(b);
        next.delete(item.id);
        return next;
      });
      // On success and on a 409 alike, so the table shows what the server has.
      await Promise.all([load(), onChanged()]);
    }
  }

  function choose(item: QueueItem, target: ClaimStatus) {
    const { override, final } = plan(item, target);
    if (final || override) setDialog({ item, target });
    else perform(item, target, "");
  }

  const dialogPlan = dialog && plan(dialog.item, dialog.target);

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Claim status" className="flex flex-wrap gap-2">
        {TABS.map(({ value, label }) => {
          const count = countFor(stats, value);
          return (
            <Button
              key={value}
              role="tab"
              aria-selected={tab === value}
              size="sm"
              variant={tab === value ? "default" : "outline"}
              onClick={() => setTab(value)}
            >
              {label}
              {count !== null && <span className="opacity-70">{count}</span>}
            </Button>
          );
        })}
      </div>

      <Card>
        <CardContent className="p-0">
          {loadError ? (
            <p className="p-6 text-sm text-destructive">{loadError}</p>
          ) : rows === null ? (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </div>
          ) : rows.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground">{EMPTY[tab]}</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="hidden border-b text-left text-xs text-muted-foreground md:table-header-group">
                <tr>
                  {["Claim", "Claimant", "Amount", "Status", "AI suggestion", "Age", "Actions"].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => {
                  const rowBusy = busy.has(item.id);
                  const sug = item.latest_suggestion;
                  const actions = VALID_TRANSITIONS[item.status];
                  return (
                    <tr
                      key={item.id}
                      onClick={() => onOpen(item.id)}
                      className="block cursor-pointer space-y-1 border-b p-3 last:border-b-0 hover:bg-accent/50 md:table-row md:space-y-0 md:p-0"
                    >
                      <Cell label="Claim">
                        <button
                          className="font-mono text-xs underline-offset-2 hover:underline"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpen(item.id);
                          }}
                        >
                          {item.id.slice(0, 8)}
                        </button>
                      </Cell>
                      <Cell label="Claimant">
                        <span className="break-words">{item.claimant_name}</span>
                      </Cell>
                      <Cell label="Amount">${item.amount.toLocaleString()}</Cell>
                      <Cell label="Status">
                        <StatusBadge status={item.status} />
                      </Cell>
                      <Cell label="AI suggestion">
                        {sug ? (
                          <span>
                            {sug.suggested_action} &middot; {(sug.confidence * 100).toFixed(0)}%
                            {sug.has_feedback && <span className="text-muted-foreground"> (answered)</span>}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">none yet</span>
                        )}
                      </Cell>
                      <Cell label="Age">{ageInDays(item.created_at)}d</Cell>
                      <Cell label="Actions">
                        {actions.length === 0 ? (
                          <span className="text-muted-foreground">Final</span>
                        ) : (
                          <div className="flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
                            {actions.map((target) => (
                              <Button
                                key={target}
                                size="sm"
                                variant={target === "denied" ? "destructive" : target === "approved" ? "default" : "secondary"}
                                disabled={rowBusy}
                                onClick={() => choose(item, target)}
                              >
                                {ACTION_LABEL[target]}
                              </Button>
                            ))}
                            {rowBusy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
                          </div>
                        )}
                      </Cell>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {rows !== null && rows.length >= PAGE_SIZE && (
        <p className="text-xs text-muted-foreground">
          Showing the oldest {PAGE_SIZE} claims in this tab. Newer ones appear as these are decided.
        </p>
      )}

      {dialog && dialogPlan && (
        <DecisionDialog
          item={dialog.item}
          label={ACTION_LABEL[dialog.target] ?? ""}
          final={dialogPlan.final}
          override={dialogPlan.override}
          onCancel={() => setDialog(null)}
          onConfirm={(note) => perform(dialog.item, dialog.target, note)}
        />
      )}

      {toast && (
        <div
          role={toast.error ? "alert" : "status"}
          className={`fixed bottom-4 right-4 z-50 max-w-sm rounded-md border bg-card p-3 text-sm shadow-lg ${
            toast.error ? "border-destructive text-destructive" : ""
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}

// On a phone each row is a stack of "label  value" lines. From md up it is a table row.
function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <td className="flex items-center justify-between gap-3 md:table-cell md:px-3 md:py-2">
      <span className="text-xs text-muted-foreground md:hidden">{label}</span>
      <span className="text-right md:text-left">{children}</span>
    </td>
  );
}
