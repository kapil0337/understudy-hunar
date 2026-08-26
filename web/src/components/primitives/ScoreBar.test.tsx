import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreBar, type ScoreBarSegment } from "./ScoreBar";

const SEGMENTS: ScoreBarSegment[] = [
  { key: "extraction_accuracy", label: "Extraction accuracy", score: 90, weight: 40 },
  { key: "coverage", label: "Coverage", score: 80, weight: 25 },
  { key: "faithfulness", label: "Faithfulness", score: 70, weight: 25 },
  { key: "efficiency", label: "Efficiency", score: 100, weight: 10 },
];

/** The bar is a flex row whose direct children are one weight-sized slot per segment, each
 * containing one score-sized fill — see ScoreBar.tsx. */
function segmentSlots(container: HTMLElement): HTMLElement[] {
  const bar = container.firstElementChild as HTMLElement;
  return Array.from(bar.children) as HTMLElement[];
}

describe("ScoreBar", () => {
  it("renders exactly one slot per segment", () => {
    const { container } = render(<ScoreBar segments={SEGMENTS} />);
    expect(segmentSlots(container)).toHaveLength(SEGMENTS.length);
  });

  it("sizes each segment's slot to its weight, and the weights total 100", () => {
    const { container } = render(<ScoreBar segments={SEGMENTS} />);
    const widths = segmentSlots(container).map((slot) => parseFloat(slot.style.width));

    expect(widths).toEqual(SEGMENTS.map((s) => s.weight));
    expect(widths.reduce((sum, w) => sum + w, 0)).toBe(100);
  });

  it("sizes each segment's fill to its own score, independent of its slot width", () => {
    const { container } = render(<ScoreBar segments={SEGMENTS} />);
    const fills = segmentSlots(container).map(
      (slot) => parseFloat((slot.firstElementChild as HTMLElement).style.width),
    );
    expect(fills).toEqual(SEGMENTS.map((s) => s.score));
  });

  it("clamps a fill to 100 even if a caller passes an out-of-range score", () => {
    const { container } = render(
      <ScoreBar segments={[{ key: "x", label: "X", score: 150, weight: 100 }]} />,
    );
    const [slot] = segmentSlots(container);
    const fill = slot.firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("100%");
  });
});
