import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunMetadata } from "../../src/components/RunMetadata";
import type { RunMetadata as RunMetadataType } from "../../src/api/types";

function mockClipboard(impl: (text: string) => Promise<void>) {
  const writeText = vi.fn(impl);
  // navigator.clipboard is a getter-only property in jsdom, so define it.
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  return writeText;
}

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

  describe("copy controls (016)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("copies the full untruncated run id (not the truncated display value)", async () => {
      // setup() first: userEvent installs its own clipboard stub on setup,
      // so our spy must be defined afterwards to win.
      const user = userEvent.setup();
      const writeText = mockClipboard(() => Promise.resolve());
      render(<RunMetadata metadata={baseMetadata} />);
      await user.click(screen.getByTestId("copy-run-id"));
      expect(writeText).toHaveBeenCalledWith(baseMetadata.run_id);
      // The display value is truncated, so the copied value must differ.
      expect(baseMetadata.run_id).not.toMatch(/…/);
    });

    it("copies the full untruncated thread id", async () => {
      const user = userEvent.setup();
      const writeText = mockClipboard(() => Promise.resolve());
      render(<RunMetadata metadata={baseMetadata} />);
      await user.click(screen.getByTestId("copy-thread-id"));
      expect(writeText).toHaveBeenCalledWith(baseMetadata.thread_id);
    });

    it("shows a copied confirmation after a successful copy", async () => {
      const user = userEvent.setup();
      mockClipboard(() => Promise.resolve());
      render(<RunMetadata metadata={baseMetadata} />);
      await user.click(screen.getByTestId("copy-run-id"));
      expect(await screen.findByText(/copied run id/i)).toBeInTheDocument();
      expect(screen.getByTestId("copy-run-id")).toHaveAccessibleName(
        /copied/i,
      );
    });

    it("exposes an accessible name on each copy control", () => {
      render(<RunMetadata metadata={baseMetadata} />);
      expect(
        screen.getByRole("button", { name: /copy run id/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /copy thread id/i }),
      ).toBeInTheDocument();
    });

    it("shows no success and does not throw when the clipboard write fails", async () => {
      const user = userEvent.setup();
      const writeText = mockClipboard(() => Promise.reject(new Error("denied")));
      render(<RunMetadata metadata={baseMetadata} />);
      await user.click(screen.getByTestId("copy-run-id"));
      expect(writeText).toHaveBeenCalledWith(baseMetadata.run_id);
      expect(screen.queryByText(/copied run id/i)).not.toBeInTheDocument();
      // Control stays in its default "Copy" state.
      expect(screen.getByTestId("copy-run-id")).toHaveAccessibleName(
        /copy run id/i,
      );
    });
  });
});
