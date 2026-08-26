import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConsentBadge, consentState } from "./ConsentBadge";

describe("consentState", () => {
  it("is 'no-phone' with no phone and no consent", () => {
    expect(consentState(false, null)).toBe("no-phone");
  });

  it("is 'phone-added' once a phone exists but consent is not yet recorded", () => {
    expect(consentState(true, null)).toBe("phone-added");
  });

  it("is 'consented' once consent_recorded_at is set", () => {
    expect(consentState(true, "2026-08-25T00:00:00Z")).toBe("consented");
  });

  it("trusts consent_recorded_at over hasPhone — a recorded consent always wins", () => {
    expect(consentState(false, "2026-08-25T00:00:00Z")).toBe("consented");
  });
});

describe("ConsentBadge", () => {
  it("renders a distinct, visible label per candidate state", () => {
    const { rerender } = render(<ConsentBadge hasPhone={false} consentRecordedAt={null} />);
    expect(screen.getByText("No phone")).toBeInTheDocument();

    rerender(<ConsentBadge hasPhone={true} consentRecordedAt={null} />);
    expect(screen.getByText("Phone added")).toBeInTheDocument();

    rerender(<ConsentBadge hasPhone={true} consentRecordedAt="2026-08-25T00:00:00Z" />);
    expect(screen.getByText("Consented")).toBeInTheDocument();
  });
});
