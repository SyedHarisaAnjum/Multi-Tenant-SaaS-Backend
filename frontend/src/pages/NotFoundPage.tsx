import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <main className="narrow-shell">
      <section className="card">
        <h1>Page not found</h1>
        <p className="muted">The page you're looking for doesn't exist.</p>
        <Link to="/orgs" className="btn">
          Go to your organizations
        </Link>
      </section>
    </main>
  );
}
