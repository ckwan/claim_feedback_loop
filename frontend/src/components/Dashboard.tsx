import { useEffect, useState } from "react";
import { api, type Claim, type ClaimStatus } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";

const STATUSES: ClaimStatus[] = ["open", "under_review", "approved", "denied"];
const PAGE = 100; // the backend caps GET /claims at 100 per page

async function listAllClaims(orgId: string): Promise<Claim[]> {
  const all: Claim[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const page = await api.listClaims(orgId, undefined, { limit: PAGE, offset });
    all.push(...page);
    if (page.length < PAGE) return all;
  }
}

export function Dashboard({ orgId }: { orgId: string }) {
  const [claims, setClaims] = useState<Claim[] | null>(null);
  const [overrideRate, setOverrideRate] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    listAllClaims(orgId).then(setClaims).catch(() => setError("Couldn't load claims."));
    api.getOverrideRate(orgId).then((r) => setOverrideRate(r.override_rate)).catch(() => {});
  }, [orgId]);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!claims) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const count = (s: ClaimStatus) => claims.filter((c) => c.status === s).length;
  const approved = count("approved");
  const denied = count("denied");
  const decided = approved + denied;
  const pct = (n: number) => `${(n * 100).toFixed(0)}%`;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Approvals &amp; denials</h2>
        <p className="text-sm text-muted-foreground">
          {claims.length} claims in this organization, counted by status.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {STATUSES.map((s) => (
          <Card key={s}>
            <CardHeader className="pb-2">
              <StatusBadge status={s} />
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-semibold">{count(s)}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Approval rate</CardTitle>
            <CardDescription>Approved out of decided claims (approved + denied).</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{decided ? pct(approved / decided) : "—"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Override rate</CardTitle>
            <CardDescription>Suggestions an adjuster overrode.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {overrideRate !== null ? pct(overrideRate) : "—"}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
