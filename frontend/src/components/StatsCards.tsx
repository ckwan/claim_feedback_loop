import type { ClaimStats, ClaimStatus } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

const STATUS_CARDS: { status: ClaimStatus; label: string }[] = [
  { status: "open", label: "Open" },
  { status: "under_review", label: "Under review" },
  { status: "approved", label: "Approved" },
  { status: "denied", label: "Denied" },
];

const percent = (rate: number | null) => (rate === null ? "—" : `${(rate * 100).toFixed(0)}%`);

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold">{value}</p>
      </CardContent>
    </Card>
  );
}

export function StatsCards({ stats }: { stats: ClaimStats }) {
  if (stats.total === 0) {
    return <p className="text-sm text-muted-foreground">No claims yet, so there are no stats to show.</p>;
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-2">
      {STATUS_CARDS.map(({ status, label }) => (
        <StatCard key={status} label={label} value={stats.by_status[status]} />
      ))}
      <StatCard label="Approval rate" value={percent(stats.approval_rate)} />
      <StatCard label="Override rate" value={percent(stats.decisions.override_rate)} />
    </div>
  );
}
