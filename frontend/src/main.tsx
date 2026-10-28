import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { AuthProvider } from "./hooks/useAuth";
import { ApiError } from "./services/api";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      // Retrying a 4xx (forbidden, not found, validation) can't succeed; only retry
      // network failures and 5xx, and only once.
      retry: (failureCount, error) =>
        failureCount < 1 && !(error instanceof ApiError && error.status < 500),
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
