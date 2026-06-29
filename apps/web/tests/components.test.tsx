import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RobustnessGauge } from "@/components/charts/gauge";
import { SeverityBadge, StatusBadge, VerdictBadge } from "@/components/ui/badges";
import { Badge } from "@/components/ui/primitives";

describe("RobustnessGauge", () => {
  it("shows the score and band for a value", () => {
    render(<RobustnessGauge value={0.92} />);
    expect(screen.getByText("92.0")).toBeInTheDocument();
    expect(screen.getByText("Robust")).toBeInTheDocument();
  });

  it("renders an em dash and 'Not evaluated' when unscored", () => {
    render(<RobustnessGauge value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Not evaluated")).toBeInTheDocument();
  });

  it("labels a gameable verifier", () => {
    render(<RobustnessGauge value={0.4} />);
    expect(screen.getByText("Gameable")).toBeInTheDocument();
  });
});

describe("badges", () => {
  it("renders a status badge", () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("renders verdicts", () => {
    const { rerender } = render(<VerdictBadge passed={true} />);
    expect(screen.getByText("Passed")).toBeInTheDocument();
    rerender(<VerdictBadge passed={false} />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("renders severity", () => {
    render(<SeverityBadge severity="critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("renders a plain badge with its children", () => {
    render(<Badge tone="info">Hello</Badge>);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});
