import { useSearchParams } from "react-router-dom";
import { useEffect } from "react";
import { SearchPanel } from "../components/SearchPanel";
import { useAppStore } from "../stores/useAppStore";

export function Search() {
  const [searchParams] = useSearchParams();
  const q = searchParams.get("q") || "";
  const { setLastQuery } = useAppStore();

  useEffect(() => {
    if (q) {
      setLastQuery(q);
    }
  }, [q, setLastQuery]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Search</h1>
      <p className="text-sm text-bb-muted">
        Search across all transcripts, tasks, and projects using hybrid (vector + fulltext) search.
      </p>
      <SearchPanel />
    </div>
  );
}
