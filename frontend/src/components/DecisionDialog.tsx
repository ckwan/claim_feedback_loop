import { useEffect, useRef, useState } from "react";
import type { QueueItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  item: QueueItem;
  label: string; // "Approve", "Deny", ...
  final: boolean;
  override: boolean; // the choice differs from a suggestion nobody has answered yet
  onCancel: () => void;
  onConfirm: (note: string) => void;
}

/** Confirm step for a final decision, or for an override that needs a reason. */
export function DecisionDialog({ item, label, final, override, onCancel, onConfirm }: Props) {
  const [note, setNote] = useState("");
  const confirmRef = useRef<HTMLButtonElement>(null);
  const missingReason = override && !note.trim();

  // The latest onCancel, so the listener is added once and focus is not pulled
  // back to the button when the parent re-renders.
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;

  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && cancelRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="decision-title"
        className="w-full max-w-md space-y-4 rounded-lg border bg-card p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="space-y-1">
          <h2 id="decision-title" className="text-lg font-semibold">
            {label} {item.claimant_name}'s claim?
          </h2>
          {final && (
            <p className="text-sm text-muted-foreground">
              This is final. An approved or denied claim can't be changed.
            </p>
          )}
        </div>

        {override && item.latest_suggestion && (
          <p className="rounded-md bg-muted/40 p-3 text-sm">
            The AI suggested <strong>{item.latest_suggestion.suggested_action}</strong>. This will
            be recorded as an override, so a reason is required.
          </p>
        )}

        <div>
          <Label htmlFor="decision-note">
            {override ? "Reason for overriding" : "Note (optional)"}
          </Label>
          <Textarea
            id="decision-note"
            className="mt-1"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {!override && (
            <p className="mt-1 text-xs text-muted-foreground">
              A note is stored only when it explains an override of the AI suggestion.
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            ref={confirmRef}
            variant={label === "Deny" ? "destructive" : "default"}
            disabled={missingReason}
            onClick={() => onConfirm(note.trim())}
          >
            Confirm {label.toLowerCase()}
          </Button>
        </div>
      </div>
    </div>
  );
}
