import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { establishSession, initToken } from "./api/client";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import "./styles.css";

initToken();
const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } } });

function mount() {
  createRoot(document.getElementById("root") as HTMLElement).render(
    <StrictMode>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </ErrorBoundary>
    </StrictMode>,
  );
}

// If a token is known, get the HttpOnly cookie BEFORE any <img>/<video> loads (no `?token=` in asset URLs).
void establishSession().finally(mount);
