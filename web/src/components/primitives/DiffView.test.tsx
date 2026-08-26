import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DiffView } from "./DiffView";

describe("DiffView", () => {
  it("leaves unchanged words unmarked", () => {
    render(<DiffView before="hello world" after="hello there" />);
    const unchanged = screen.getByText("hello");
    expect(unchanged).not.toHaveClass("text-status-failed");
    expect(unchanged).not.toHaveClass("text-status-completed");
  });

  it("marks a removed word as deleted (struck through, failed colour)", () => {
    render(<DiffView before="hello world" after="hello there" />);
    const removed = screen.getByText("world");
    expect(removed).toHaveClass("line-through");
    expect(removed).toHaveClass("text-status-failed");
  });

  it("marks an added word as inserted (completed colour, no strike-through)", () => {
    render(<DiffView before="hello world" after="hello there" />);
    const added = screen.getByText("there");
    expect(added).toHaveClass("text-status-completed");
    expect(added).not.toHaveClass("line-through");
  });

  it("marks nothing when before and after are identical", () => {
    const { container } = render(<DiffView before="same text" after="same text" />);
    expect(container.querySelectorAll(".text-status-failed, .text-status-completed")).toHaveLength(
      0,
    );
  });
});
