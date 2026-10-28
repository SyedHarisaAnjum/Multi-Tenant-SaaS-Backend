/** "Acme Inc." → "acme-inc" (matches the backend's slug rule). */
export function slugify(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  // Date-only values ("2030-01-31") are calendar dates, not instants: don't shift by timezone.
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
  return dateFormat.format(date);
}

export function isOverdue(due: string | null, status: string): boolean {
  if (!due || status === "done") return false;
  return new Date(`${due}T23:59:59`) < new Date();
}
