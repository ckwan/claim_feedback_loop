import { useState } from "react";
import { api, type Investigation } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, Telescope } from "lucide-react";

const STOP_LABEL: Record<Investigation["stopped_because"], string> = {
  finished: "finished",
  step_limit: "stopped at the step limit",
  repeated_action: "stopped: repeated a step",
  error: "stopped: the model gave no usable step",
};

export function InvestigationPanel({ orgId, claimId }: { orgId: string; claimId: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Investigation | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.investigateClaim(orgId, claimId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button variant="ghost" size="sm" className="gap-2 self-start" onClick={run} disabled={loading}>
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Telescope className="h-4 w-4" />}
        Investigate with the ReAct agent
      </Button>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {result && (
        <div className="space-y-3 rounded-md border bg-muted/30 p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-medium">Answer</span>
            <Badge variant={result.stopped_because === "finished" ? "success" : "warning"}>
              {STOP_LABEL[result.stopped_because]}
            </Badge>
          </div>
          <p>{result.answer}</p>
          {result.cited_claim_ids.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Based on claims: {result.cited_claim_ids.map((id) => id.slice(0, 8)).join(", ")}
            </p>
          )}
          <ol className="space-y-2 border-t pt-2">
            {result.steps.map((s) => (
              <li key={s.step} className="space-y-0.5">
                <p className="text-xs text-muted-foreground">
                  Step {s.step}: {s.thought}
                </p>
                <p className="font-mono text-xs">
                  {s.action}({JSON.stringify(s.args)})
                </p>
                <p className="line-clamp-3 text-xs text-muted-foreground">{s.observation}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
