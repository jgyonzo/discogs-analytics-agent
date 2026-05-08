import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SqlViewer } from "../../src/components/SqlViewer";

describe("SqlViewer", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders nothing when sql is null", () => {
    const { container } = render(<SqlViewer sql={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when sql is an empty string", () => {
    const { container } = render(<SqlViewer sql="" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when sql is whitespace only", () => {
    const { container } = render(<SqlViewer sql={"   \n  "} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a collapsed panel by default when sql is non-empty", () => {
    render(<SqlViewer sql="SELECT 1" />);
    // Header button is visible.
    expect(
      screen.getByRole("button", { name: /Generated SQL/i }),
    ).toBeInTheDocument();
    // Body is NOT visible (collapsed).
    expect(screen.queryByText("SELECT 1")).not.toBeInTheDocument();
    // No copy button until expanded.
    expect(
      screen.queryByRole("button", { name: /Copy SQL to clipboard/i }),
    ).not.toBeInTheDocument();
  });

  it("expands to reveal SQL and a copy button when the header is clicked", async () => {
    const user = userEvent.setup();
    render(<SqlViewer sql="SELECT decade FROM release_unique_view" />);
    await user.click(screen.getByRole("button", { name: /Generated SQL/i }));
    expect(
      screen.getByText("SELECT decade FROM release_unique_view"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Copy SQL to clipboard/i }),
    ).toBeInTheDocument();
  });

  it("calls navigator.clipboard.writeText with the exact SQL when copy is clicked", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    const sql = "SELECT decade, COUNT(*) FROM release_unique_view GROUP BY 1";
    render(<SqlViewer sql={sql} />);

    await user.click(screen.getByRole("button", { name: /Generated SQL/i }));
    await user.click(
      screen.getByRole("button", { name: /Copy SQL to clipboard/i }),
    );

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(sql);

    vi.unstubAllGlobals();
  });

  it("flips the copy icon to a checkmark after click", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });

    render(<SqlViewer sql="SELECT 1" />);
    await user.click(screen.getByRole("button", { name: /Generated SQL/i }));
    await user.click(
      screen.getByRole("button", { name: /Copy SQL to clipboard/i }),
    );

    // After click, the button now shows "Copied" instead of "Copy".
    expect(
      await screen.findByRole("button", { name: /Copy SQL to clipboard/i }),
    ).toHaveTextContent(/Copied/i);

    vi.unstubAllGlobals();
  });

  it("collapses again when the header is clicked a second time", async () => {
    const user = userEvent.setup();
    render(<SqlViewer sql="SELECT 1" />);
    const header = screen.getByRole("button", { name: /Generated SQL/i });
    await user.click(header);
    expect(screen.getByText("SELECT 1")).toBeInTheDocument();
    await user.click(header);
    expect(screen.queryByText("SELECT 1")).not.toBeInTheDocument();
  });
});
