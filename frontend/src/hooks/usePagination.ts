import { useCallback, useEffect, useMemo, useState } from "react";

export function usePagination<T>(items: T[], pageSize: number) {
  const [page, setPage] = useState(1);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(items.length / pageSize)),
    [items.length, pageSize]
  );

  // Clamp page when items shrink (e.g. after delete or search filter).
  useEffect(() => {
    setPage((p) => Math.min(p, Math.max(1, Math.ceil(items.length / pageSize))));
  }, [items.length, pageSize]);

  // Jump to page 1 when the list changes substantially (new upload or search).
  const resetPage = useCallback(() => setPage(1), []);

  const pageItems = useMemo(
    () => items.slice((page - 1) * pageSize, page * pageSize),
    [items, page, pageSize]
  );

  return { page, setPage, totalPages, pageItems, resetPage };
}
