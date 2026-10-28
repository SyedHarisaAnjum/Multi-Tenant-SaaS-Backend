import type { ReactNode } from "react";

export function AuthLayout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="auth-shell">
      <div className="auth-card">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          TeamFlow
        </div>
        <h1>{title}</h1>
        {children}
      </div>
    </main>
  );
}
