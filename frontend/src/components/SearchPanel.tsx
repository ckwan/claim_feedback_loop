import { useState } from "react";
import { api, type SearchHit, type SearchMode, type SearchResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { Loader2, Search } from "lucide-react";

const MODES: { value: SearchMode; label: string; help: string }[] = [
  { value: "hybrid", label: "Hybrid", help: "Meaning and keywords, merged" },
  { value: "vector", label: "Meaning", help: "Embeddings only (pgvector)" },
  { value: "keyword", label: "Keyword", help: "Full text search only" },
];

function RankBadges({ hit }: { hit: SearchHit }) {
  return (
    <div className="flex flex-wrap gap-1">
      {hit.vector_rank !== null && <Badge variant="outline">meaning #{hit.vector_rank}</Badge>}
      {hit.keyword_rank !== null && <Badge variant="outline">keyword #{hit.keyword_rank}</Badge>}
      {hit.rerank_score !== null && <Badge variant="secondary">rerank {hit.rerank_score}/10</Badge>}
    </div>
  );
}

export function SearchPanel({ orgId, onOpen }: { orgId: string; onOpen: (claimId: string) => void }) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [rerank, setRerank] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<SearchResponse | null>(null);

  async function run() {
    if (query.trim().length < 2) return;
    setLoading(true);
    setError(null);
    try {
      setResponse(await api.searchClaims(orgId, query.trim(), { mode, rerank }));
    } catch (e) {
      setResponse(null);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Search claim history</CardTitle>
        <CardDescription>Find similar past claims in this organization.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
        >
          <Input
            aria-label="Search query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. water damage from a pipe"
          />
          <Button type="submit" size="sm" disabled={loading || query.trim().length < 2} aria-label="Search">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          </Button>
        </form>

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <div className="inline-flex rounded-md border p-0.5" role="group" aria-label="Search method">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                title={m.help}
                onClick={() => setMode(m.value)}
                className={`rounded px-2 py-1 text-xs ${mode === m.value ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
            Rerank with the LLM
          </label>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {response && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {response.results.length} result{response.results.length === 1 ? "" : "s"} &middot;{" "}
              {response.mode}
              {response.reranked ? " + rerank" : ""} &middot; {response.embedding_model} &middot;{" "}
              {Object.entries(response.timings_ms)
                .map(([k, v]) => `${k} ${v}ms`)
                .join(", ")}
            </p>
            {response.results.length === 0 && (
              <p className="text-sm text-muted-foreground">No matching claims.</p>
            )}
            {response.results.map((hit) => (
              <button
                key={hit.claim_id}
                type="button"
                onClick={() => onOpen(hit.claim_id)}
                className="w-full space-y-1.5 rounded-md border p-2.5 text-left text-sm transition-colors hover:bg-accent"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">{hit.claimant_name}</span>
                  <StatusBadge status={hit.status} />
                </div>
                <p className="text-muted-foreground">{hit.snippet}</p>
                <RankBadges hit={hit} />
              </button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
