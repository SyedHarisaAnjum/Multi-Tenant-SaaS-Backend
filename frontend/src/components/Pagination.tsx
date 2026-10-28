interface Props {
  page: number;
  totalPages: number;
  total: number;
  onChange: (page: number) => void;
}

export function Pagination({ page, totalPages, total, onChange }: Props) {
  if (totalPages <= 1) return <p className="muted small">{total} total</p>;
  return (
    <nav className="pagination" aria-label="Pagination">
      <button type="button" className="btn btn-small" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Previous
      </button>
      <span className="muted small">
        Page {page} of {totalPages} · {total} total
      </span>
      <button
        type="button"
        className="btn btn-small"
        disabled={page >= totalPages}
        onClick={() => onChange(page + 1)}
      >
        Next →
      </button>
    </nav>
  );
}
