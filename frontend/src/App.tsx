import { useEffect, useState } from "react";
import { api, type Claim } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { StatusBadge } from "@/components/StatusBadge";
import { ClaimDetail } from "@/components/ClaimDetail";
import { SearchPanel } from "@/components/SearchPanel";
import { Plus, Gauge } from "lucide-react";

export default function App() {
  const [orgId, setOrgId] = useState<string | null>(
    () => localStorage.getItem("claims_org_id")
  );
  const [adjusterId, setAdjusterId] = useState<string | null>(
    () => localStorage.getItem("claims_adjuster_id")
  );
  const [adjusterName, setAdjusterName] = useState<string | null>(
    () => localStorage.getItem("claims_adjuster_name")
  );

  const [claims, setClaims] = useState<Claim[]>([]);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  // A claim opened from search may not be on the first page of the list.
  const [openedClaim, setOpenedClaim] = useState<Claim | null>(null);
  const [overrideRate, setOverrideRate] = useState<number | null>(null);

  const [newClaimant, setNewClaimant] = useState("");
  const [newAmount, setNewAmount] = useState("");
  const [newNotes, setNewNotes] = useState("");

  async function refreshClaims(org: string) {
    const list = await api.listClaims(org);
    setClaims(list);
    const rate = await api.getOverrideRate(org).catch(() => null);
    if (rate) setOverrideRate(rate.override_rate);
  }

  useEffect(() => {
    if (orgId) refreshClaims(orgId).catch(() => {});
  }, [orgId]);

  async function handleSetup(orgName: string, adjName: string, adjEmail: string) {
    const org = await api.createOrganization(orgName);
    const adj = await api.createAdjuster(org.id, adjName, adjEmail);
    localStorage.setItem("claims_org_id", org.id);
    localStorage.setItem("claims_adjuster_id", adj.id);
    localStorage.setItem("claims_adjuster_name", adj.name);
    setOrgId(org.id);
    setAdjusterId(adj.id);
    setAdjusterName(adj.name);
  }

  async function handleCreateClaim() {
    if (!orgId || !newClaimant || !newAmount) return;
    await api.createClaim(orgId, {
      claimant_name: newClaimant,
      amount: parseFloat(newAmount),
      history_notes: newNotes || undefined,
    });
    setNewClaimant("");
    setNewAmount("");
    setNewNotes("");
    refreshClaims(orgId);
  }

  if (!orgId) {
    return <SetupScreen onSubmit={handleSetup} />;
  }

  const selectedClaim =
    claims.find((c) => c.id === selectedClaimId) ??
    (openedClaim && openedClaim.id === selectedClaimId ? openedClaim : null);

  async function openFromSearch(claimId: string) {
    const claim = await api.getClaim(orgId!, claimId);
    setOpenedClaim(claim);
    setSelectedClaimId(claimId);
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="container flex items-center justify-between py-4">
          <div>
            <h1 className="text-xl font-semibold">Claims Feedback Loop</h1>
            <p className="text-sm text-muted-foreground">
              Signed in as {adjusterName} &middot; org {orgId.slice(0, 8)}
            </p>
          </div>
          {overrideRate !== null && (
            <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
              <Gauge className="h-4 w-4 text-muted-foreground" />
              Override rate: <span className="font-medium">{(overrideRate * 100).toFixed(0)}%</span>
            </div>
          )}
        </div>
      </header>

      <main className="container grid grid-cols-1 gap-6 py-8 lg:grid-cols-[360px_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">New claim</CardTitle>
              <CardDescription>Create a claim to generate a suggestion for.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label htmlFor="claimant">Claimant name</Label>
                <Input
                  id="claimant"
                  value={newClaimant}
                  onChange={(e) => setNewClaimant(e.target.value)}
                  placeholder="Jane Doe"
                />
              </div>
              <div>
                <Label htmlFor="amount">Amount requested</Label>
                <Input
                  id="amount"
                  type="number"
                  value={newAmount}
                  onChange={(e) => setNewAmount(e.target.value)}
                  placeholder="500"
                />
              </div>
              <div>
                <Label htmlFor="notes">History notes</Label>
                <Input
                  id="notes"
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  placeholder="Minor fender bender, no injuries"
                />
              </div>
              <Button
                className="w-full gap-2"
                onClick={handleCreateClaim}
                disabled={!newClaimant || !newAmount}
              >
                <Plus className="h-4 w-4" />
                Create claim
              </Button>
            </CardContent>
          </Card>

          <SearchPanel orgId={orgId} onOpen={(id) => openFromSearch(id).catch(() => {})} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Claims</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {claims.length === 0 && (
                <p className="text-sm text-muted-foreground">No claims yet.</p>
              )}
              {claims.map((claim) => (
                <button
                  key={claim.id}
                  onClick={() => setSelectedClaimId(claim.id)}
                  className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
                    selectedClaimId === claim.id ? "bg-accent" : ""
                  }`}
                >
                  <span className="truncate">{claim.claimant_name}</span>
                  <StatusBadge status={claim.status} />
                </button>
              ))}
            </CardContent>
          </Card>
        </div>

        <div>
          {selectedClaim ? (
            <ClaimDetail
              orgId={orgId}
              adjusterId={adjusterId}
              claim={selectedClaim}
              onChanged={() => refreshClaims(orgId)}
            />
          ) : (
            <Card className="flex h-full min-h-[300px] items-center justify-center">
              <p className="text-sm text-muted-foreground">
                Select a claim on the left, or create one to get started.
              </p>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}

function SetupScreen({
  onSubmit,
}: {
  onSubmit: (orgName: string, adjName: string, adjEmail: string) => Promise<void>;
}) {
  const [orgName, setOrgName] = useState("Acme Insurance");
  const [adjName, setAdjName] = useState("");
  const [adjEmail, setAdjEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    try {
      await onSubmit(orgName, adjName, adjEmail);
    } catch (e) {
      setError(
        "Couldn't reach the backend. Make sure the FastAPI server is running " +
          "(see the project README) and VITE_API_BASE_URL points at it."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Claims Feedback Loop</CardTitle>
          <CardDescription>
            One-time setup: creates an org and an adjuster to work as.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <Label htmlFor="org-name">Organization name</Label>
            <Input id="org-name" value={orgName} onChange={(e) => setOrgName(e.target.value)} />
          </div>
          <Separator />
          <div>
            <Label htmlFor="adj-name">Your name (adjuster)</Label>
            <Input id="adj-name" value={adjName} onChange={(e) => setAdjName(e.target.value)} placeholder="Jane SME" />
          </div>
          <div>
            <Label htmlFor="adj-email">Your email</Label>
            <Input id="adj-email" value={adjEmail} onChange={(e) => setAdjEmail(e.target.value)} placeholder="jane@acme.com" />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button
            className="w-full"
            onClick={handleSubmit}
            disabled={loading || !orgName || !adjName || !adjEmail}
          >
            {loading ? "Setting up…" : "Start"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
