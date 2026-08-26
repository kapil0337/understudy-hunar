import { describe, expect, it } from "vitest";
import { hasNonTerminalRow } from "./useBoard";
import type { BoardRow } from "@/lib/api/schemas";

function row(overrides: Partial<BoardRow>): BoardRow {
  return {
    candidate_id: "00000000-0000-0000-0000-000000000001",
    full_name: "Test Candidate",
    match_score: null,
    phone_e164: null,
    consent_recorded_at: null,
    dnc: false,
    outreach_id: null,
    agent_version_id: null,
    status: null,
    lifecycle_status: null,
    duration_seconds: null,
    recording_url: null,
    result: null,
    call_summary: null,
    is_simulated: false,
    ...overrides,
  };
}

describe("hasNonTerminalRow", () => {
  it("is true while a row is still in flight (RINGING)", () => {
    expect(hasNonTerminalRow([row({ status: "RINGING" })])).toBe(true);
  });

  it("is false once every row has landed on a terminal status", () => {
    const rows = [
      row({ status: "COMPLETED" }),
      row({ status: "NOT_CONNECTED" }),
      row({ status: "FAILED" }),
      row({ status: "CANCELLED" }),
    ];
    expect(hasNonTerminalRow(rows)).toBe(false);
  });

  it("treats a never-called row (status null) as nothing to poll for, not in flight", () => {
    expect(hasNonTerminalRow([row({ status: null })])).toBe(false);
  });

  it("stays true if even one row among many terminal ones is still in flight", () => {
    const rows = [
      row({ status: "COMPLETED" }),
      row({ status: "IN_PROGRESS" }),
      row({ status: "FAILED" }),
    ];
    expect(hasNonTerminalRow(rows)).toBe(true);
  });

  it("is false for an empty board", () => {
    expect(hasNonTerminalRow([])).toBe(false);
  });
});
