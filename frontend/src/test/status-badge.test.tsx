import { toneForStatus } from "../components/StatusBadge";

describe("StatusBadge semantics", () => {
  it.each([
    ["not extracted", "danger"],
    ["not available", "danger"],
    ["not ready", "danger"],
    ["not generated", "danger"],
    ["ai_reviewed", "warn"],
    ["stale", "warn"],
    ["approved", "good"],
  ])("maps %s to %s without positive substring collisions", (label, expected) => {
    expect(toneForStatus(label)).toBe(expected);
  });
});
