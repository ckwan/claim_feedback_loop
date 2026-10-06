import { Badge } from "@/components/ui/badge";
import type { ClaimStatus } from "@/lib/api";

const VARIANT: Record<ClaimStatus, "secondary" | "warning" | "success" | "destructive"> = {
  open: "secondary",
  under_review: "warning",
  approved: "success",
  denied: "destructive",
};

const LABEL: Record<ClaimStatus, string> = {
  open: "Open",
  under_review: "Under Review",
  approved: "Approved",
  denied: "Denied",
};

export function StatusBadge({ status }: { status: ClaimStatus }) {
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>;
}
