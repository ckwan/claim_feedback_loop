import { useState } from "react";
import { api, type Claim, type ClaimEditPayload } from "@/lib/api";
import { detailOf } from "@/components/ReviewActions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Loader2 } from "lucide-react";

const MAX_NOTES = 5000; // same limit as the backend

const FIELD_LABEL = { claimant_name: "Claimant", amount: "Amount", history_notes: "History notes" } as const;

interface Props {
  orgId: string;
  adjusterId: string | null;
  claim: Claim;
  onCancel: () => void;
  onSaved: (changed: (keyof typeof FIELD_LABEL)[]) => void;
}

export function ClaimEditForm({ orgId, adjusterId, claim, onCancel, onSaved }: Props) {
  const [name, setName] = useState(claim.claimant_name);
  const [amount, setAmount] = useState(String(claim.amount));
  const [notes, setNotes] = useState(claim.history_notes ?? "");
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const amountNumber = Number(amount);
  const errors = {
    name: !name.trim() ? "Claimant name is required." : name.length > 255 ? "Keep it under 255 characters." : null,
    amount:
      !amount.trim() || Number.isNaN(amountNumber) || amountNumber <= 0 ? "Amount must be greater than 0." : null,
    notes: notes.length > MAX_NOTES ? `Notes are limited to ${MAX_NOTES} characters.` : null,
  };
  const valid = !errors.name && !errors.amount && !errors.notes;

  // Only what differs is sent. Clearing the notes sends null.
  const changes: ClaimEditPayload = {};
  if (valid) {
    if (name.trim() !== claim.claimant_name) changes.claimant_name = name.trim();
    if (amountNumber !== claim.amount) changes.amount = amountNumber;
    if ((notes.trim() || null) !== (claim.history_notes || null)) changes.history_notes = notes.trim() || null;
  }
  const changedFields = Object.keys(changes) as (keyof typeof FIELD_LABEL)[];
  const staleWarning = changedFields.includes("amount") || changedFields.includes("history_notes");

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.editClaim(orgId, claim.id, { ...changes, adjuster_id: adjusterId ?? undefined });
      onSaved(changedFields);
    } catch (e) {
      setError(detailOf(e));
      setConfirming(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 rounded-md border p-4">
      <div>
        <Label htmlFor="edit-name">Claimant name</Label>
        <Input id="edit-name" value={name} onChange={(e) => setName(e.target.value)} disabled={saving} />
        {errors.name && <p className="mt-1 text-xs text-destructive">{errors.name}</p>}
      </div>
      <div>
        <Label htmlFor="edit-amount">Amount</Label>
        <Input
          id="edit-amount"
          type="number"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          disabled={saving}
        />
        {errors.amount && <p className="mt-1 text-xs text-destructive">{errors.amount}</p>}
      </div>
      <div>
        <Label htmlFor="edit-notes">History notes</Label>
        <Textarea id="edit-notes" value={notes} onChange={(e) => setNotes(e.target.value)} disabled={saving} />
        <p className={`mt-1 text-xs ${errors.notes ? "text-destructive" : "text-muted-foreground"}`}>
          {errors.notes ?? `${notes.length} / ${MAX_NOTES}`}
        </p>
      </div>

      {confirming ? (
        <div className="space-y-2 rounded-md bg-muted/40 p-3">
          <p className="text-sm font-medium">Save these changes?</p>
          <ul className="space-y-1 text-sm">
            {changedFields.map((f) => (
              <li key={f}>
                <span className="text-muted-foreground">{FIELD_LABEL[f]}:</span>{" "}
                {f === "history_notes" ? "updated" : `${f === "amount" ? claim.amount : claim.claimant_name} → ${changes[f]}`}
              </li>
            ))}
          </ul>
          {staleWarning && (
            <p className="text-xs text-amber-700">
              Earlier AI suggestions will be marked out of date. You'll need to request a new one.
            </p>
          )}
          <div className="flex gap-2">
            <Button size="sm" disabled={saving} onClick={save} className="gap-2">
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              Confirm and save
            </Button>
            <Button size="sm" variant="ghost" disabled={saving} onClick={() => setConfirming(false)}>
              Back
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Button size="sm" disabled={!valid || changedFields.length === 0} onClick={() => setConfirming(true)}>
            Save changes
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          {valid && changedFields.length === 0 && (
            <span className="text-xs text-muted-foreground">No changes yet.</span>
          )}
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
