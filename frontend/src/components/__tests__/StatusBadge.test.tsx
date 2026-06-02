import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("renders active status with correct styling", () => {
    render(<StatusBadge status="active" />);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("renders completed status", () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("renders in_progress status", () => {
    render(<StatusBadge status="in_progress" />);
    expect(screen.getByText("In Progress")).toBeInTheDocument();
  });

  it("renders abandoned status", () => {
    render(<StatusBadge status="abandoned" />);
    expect(screen.getByText("Abandoned")).toBeInTheDocument();
  });

  it("renders todo status", () => {
    render(<StatusBadge status="todo" />);
    expect(screen.getByText("Todo")).toBeInTheDocument();
  });

  it("renders unknown status as-is", () => {
    render(<StatusBadge status="custom_status" />);
    expect(screen.getByText("custom_status")).toBeInTheDocument();
  });
});
