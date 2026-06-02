import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatsCards } from "../StatsCards";
import type { Stats } from "../../api/types";

const mockStats: Stats = {
  total_sources: 42,
  total_transcripts: 128,
  total_projects: 15,
  total_tasks: 64,
  total_artifacts: 256,
  total_messages: 1024,
  provider_breakdown: { claude_code: 80, codex: 30, kimi: 18 },
  status_breakdown: { processed: 100, pending: 28 },
};

describe("StatsCards", () => {
  it("renders loading state", () => {
    render(<StatsCards stats={undefined} isLoading={true} />);
    expect(document.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders all stat cards with correct values", () => {
    render(<StatsCards stats={mockStats} isLoading={false} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("128")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("64")).toBeInTheDocument();
    expect(screen.getByText("256")).toBeInTheDocument();
    expect(screen.getByText("1,024")).toBeInTheDocument();
  });

  it("renders all card labels", () => {
    render(<StatsCards stats={mockStats} isLoading={false} />);
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("Transcripts")).toBeInTheDocument();
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("Tasks")).toBeInTheDocument();
    expect(screen.getByText("Artifacts")).toBeInTheDocument();
    expect(screen.getByText("Messages")).toBeInTheDocument();
  });
});
