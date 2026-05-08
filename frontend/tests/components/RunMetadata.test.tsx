import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunMetadata } from "../../src/components/RunMetadata";
import type { RunMetadata as RunMetadataType } from "../../src/api/types";

const baseMetadata: RunMetadataType = {
  run_id: "run-abc-12345678",
  thread_id: "thread-xyz-87654321",
  complexity: "simple",
  selected_model: "gpt-4o-mini",
  rationale: "Single-table aggregation by decade.",
  status: "succeeded",
};

describe("RunMetadata", () => {
  it("renders nothing when metadata is null", () => {
    const { container } = render(<RunMetadata metadata={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders all 5 badges when every field is populated", () => {
    render(<RunMetadata metadata={baseMetadata} />);
    expect(screen.getByTestId("run-metadata-status")).toHaveTextContent(/succeeded/);
    expect(screen.getByTestId("run-metadata-complexity")).toHaveTextContent(/simple/);
    expect(screen.getByTestId("run-metadata-model")).toHaveTextContent(/gpt-4o-mini/);
    expect(screen.getByTestId("run-metadata-run-id")).toHaveTextContent(/run-ab/);
    expect(screen.getByTestId("run-metadata-thread-id")).toHaveTextContent(
      /thread/,
    );
  });

  it("hides the complexity badge when the field is missing", () => {
    const { complexity: _, ...rest } = baseMetadata;
    void _;
    render(<RunMetadata metadata={rest} />);
    expect(
      screen.queryByTestId("run-metadata-complexity"),
    ).not.toBeInTheDocument();
    // Other badges still render.
    expect(screen.getByTestId("run-metadata-status")).toBeInTheDocument();
  });

  it("hides the model badge when selected_model is null", () => {
    render(
      <RunMetadata metadata={{ ...baseMetadata, selected_model: null }} />,
    );
    expect(
      screen.queryByTestId("run-metadata-model"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("run-metadata-status")).toBeInTheDocument();
  });

  it("never renders the literal text 'null' or 'undefined'", () => {
    render(
      <RunMetadata
        metadata={{
          ...baseMetadata,
          selected_model: null,
          complexity: undefined,
        }}
      />,
    );
    const wrapper = screen.getByTestId("run-metadata");
    expect(wrapper.textContent).not.toMatch(/\bnull\b/);
    expect(wrapper.textContent).not.toMatch(/\bundefined\b/);
  });

  it("truncates long ids in the run and thread badges", () => {
    render(<RunMetadata metadata={baseMetadata} />);
    const runBadge = screen.getByTestId("run-metadata-run-id");
    expect(runBadge.textContent).not.toContain(baseMetadata.run_id);
    expect(runBadge.textContent).toMatch(/run-ab/); // first 6 chars retained
  });

  it("applies a green-tinted style for succeeded status", () => {
    render(<RunMetadata metadata={baseMetadata} />);
    const status = screen.getByTestId("run-metadata-status");
    expect(status.className).toMatch(/green/);
  });

  it("applies a red-tinted style for failed_safety status", () => {
    render(
      <RunMetadata
        metadata={{ ...baseMetadata, status: "failed_safety" }}
      />,
    );
    const status = screen.getByTestId("run-metadata-status");
    expect(status.className).toMatch(/red/);
  });

  it("applies a slate-tinted style for failed_unsupported status", () => {
    render(
      <RunMetadata
        metadata={{ ...baseMetadata, status: "failed_unsupported" }}
      />,
    );
    const status = screen.getByTestId("run-metadata-status");
    expect(status.className).toMatch(/slate/);
  });
});
