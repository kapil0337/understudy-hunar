import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it.each([
    ["NOT_STARTED", "Not started"],
    ["RINGING", "Ringing"],
    ["IN_PROGRESS", "In progress"],
    ["COMPLETED", "Completed"],
    ["NOT_CONNECTED", "Not connected"],
    ["FAILED", "Failed"],
  ] as const)("renders %s as visible text, not colour alone", (status, label) => {
    render(<StatusPill status={status} kind="call" />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("labels a rehearsal run status the same way", () => {
    render(<StatusPill status="RUNNING" kind="run" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});
