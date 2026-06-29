import { describe, expect, it } from "vitest";

import {
  BAND_LABEL, categoryLabel, pct, relativeTime, riskBand, robustnessBand,
  score, shortHash, statusTone, titleCase,
} from "@/lib/format";

describe("pct", () => {
  it("formats a fraction as a percentage", () => {
    expect(pct(0.5)).toBe("50.0%");
    expect(pct(0.1234, 1)).toBe("12.3%");
    expect(pct(1)).toBe("100.0%");
  });
  it("renders an em dash for missing values", () => {
    expect(pct(null)).toBe("—");
    expect(pct(undefined)).toBe("—");
    expect(pct(NaN)).toBe("—");
  });
});

describe("score", () => {
  it("fixes to the requested precision", () => {
    expect(score(0.5)).toBe("0.500");
    expect(score(1, 2)).toBe("1.00");
  });
  it("dashes missing values", () => {
    expect(score(null)).toBe("—");
  });
});

describe("shortHash", () => {
  it("truncates long hashes with an ellipsis", () => {
    expect(shortHash("abcdef1234567890", 8)).toBe("abcdef12…");
  });
  it("returns short values unchanged", () => {
    expect(shortHash("abc", 8)).toBe("abc");
  });
  it("dashes empty values", () => {
    expect(shortHash(null)).toBe("—");
  });
});

describe("relativeTime", () => {
  const now = new Date("2026-06-28T12:00:00Z").getTime();
  it("handles seconds, minutes, hours, days", () => {
    expect(relativeTime("2026-06-28T11:59:30Z", now)).toBe("30s ago");
    expect(relativeTime("2026-06-28T11:30:00Z", now)).toBe("30m ago");
    expect(relativeTime("2026-06-28T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-06-25T12:00:00Z", now)).toBe("3d ago");
  });
  it("dashes invalid input", () => {
    expect(relativeTime(null, now)).toBe("—");
    expect(relativeTime("not-a-date", now)).toBe("—");
  });
});

describe("robustnessBand", () => {
  it("classifies by threshold", () => {
    expect(robustnessBand(0.95)).toBe("strong");
    expect(robustnessBand(0.8)).toBe("fair");
    expect(robustnessBand(0.4)).toBe("weak");
    expect(robustnessBand(null)).toBe("unknown");
  });
  it("has a label for every band", () => {
    expect(BAND_LABEL.strong).toBe("Robust");
    expect(BAND_LABEL.weak).toBe("Gameable");
  });
});

describe("riskBand", () => {
  it("treats higher risk as weaker", () => {
    expect(riskBand(0.7)).toBe("weak");
    expect(riskBand(0.4)).toBe("fair");
    expect(riskBand(0.1)).toBe("strong");
    expect(riskBand(null)).toBe("unknown");
  });
});

describe("statusTone", () => {
  it("maps lifecycle statuses to tones", () => {
    expect(statusTone("completed")).toBe("pass");
    expect(statusTone("running")).toBe("warn");
    expect(statusTone("pending")).toBe("muted");
    expect(statusTone("failed")).toBe("risk");
  });
});

describe("categoryLabel / titleCase", () => {
  it("humanizes known categories", () => {
    expect(categoryLabel("judge_manipulation")).toBe("Judge manipulation");
    expect(categoryLabel("length_bias")).toBe("Length bias");
  });
  it("title-cases snake/kebab strings", () => {
    expect(titleCase("reward_hacking.flagged")).toBe("Reward Hacking.Flagged");
    expect(titleCase("model-generated")).toBe("Model Generated");
  });
});
