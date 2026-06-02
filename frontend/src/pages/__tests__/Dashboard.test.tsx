import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter } from "react-router-dom";
import { Dashboard } from "../Dashboard";

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

describe("Dashboard", () => {
  it("renders dashboard heading", () => {
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <HashRouter>
          <Dashboard />
        </HashRouter>
      </QueryClientProvider>
    );
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders quick action buttons", () => {
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <HashRouter>
          <Dashboard />
        </HashRouter>
      </QueryClientProvider>
    );
    expect(screen.getByText("Search")).toBeInTheDocument();
    expect(screen.getByText("Ingest")).toBeInTheDocument();
    expect(screen.getByText("Export")).toBeInTheDocument();
  });
});
