import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataPreviewTable } from "../../src/components/DataPreviewTable";

describe("DataPreviewTable", () => {
  it("renders the empty placeholder when rows is empty", () => {
    render(<DataPreviewTable rows={[]} />);
    expect(
      screen.getByText(/No data preview available\./i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("data-preview-table")).not.toBeInTheDocument();
  });

  it("renders 5 rows with column headers inferred from row 0", () => {
    const rows = [
      { decade: 1980, releases: 120 },
      { decade: 1990, releases: 450 },
      { decade: 2000, releases: 890 },
      { decade: 2010, releases: 1200 },
      { decade: 2020, releases: 600 },
    ];
    render(<DataPreviewTable rows={rows} />);
    const table = screen.getByTestId("data-preview-table");
    // Header cells.
    expect(within(table).getByText("decade")).toBeInTheDocument();
    expect(within(table).getByText("releases")).toBeInTheDocument();
    // Body rows.
    const bodyRows = table.querySelectorAll("tbody tr");
    expect(bodyRows.length).toBe(5);
    // Specific cells.
    expect(within(table).getByText("1980")).toBeInTheDocument();
    expect(within(table).getByText("1200")).toBeInTheDocument();
  });

  it("caps display at 20 rows even when given 25", () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({
      idx: i,
      label: `row-${i}`,
    }));
    render(<DataPreviewTable rows={rows} />);
    const table = screen.getByTestId("data-preview-table");
    const bodyRows = table.querySelectorAll("tbody tr");
    expect(bodyRows.length).toBe(20);
    // First 20 are visible; last 5 are not.
    expect(within(table).getByText("row-0")).toBeInTheDocument();
    expect(within(table).getByText("row-19")).toBeInTheDocument();
    expect(within(table).queryByText("row-20")).not.toBeInTheDocument();
    expect(within(table).queryByText("row-24")).not.toBeInTheDocument();
  });

  it("renders non-primitive cell values as JSON-stringified text", () => {
    const rows = [{ name: "x", payload: { nested: 42 } }];
    render(<DataPreviewTable rows={rows} />);
    expect(screen.getByText('{"nested":42}')).toBeInTheDocument();
  });

  it("renders null and undefined cells as empty", () => {
    const rows = [{ a: null, b: undefined, c: "kept" }];
    render(<DataPreviewTable rows={rows} />);
    expect(screen.getByText("kept")).toBeInTheDocument();
    // The row has 3 cells; only "kept" has visible text.
    const table = screen.getByTestId("data-preview-table");
    const cells = table.querySelectorAll("tbody td");
    expect(cells.length).toBe(3);
  });
});
