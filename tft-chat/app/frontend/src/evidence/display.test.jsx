import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvidenceDisplay } from "./display.jsx";
import { distributionPresentation, rankingPresentation } from "./fixtures.js";
import { visibleRows } from "./utils.js";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Evidence displays", () => {
  it("renders a readable static table with context, rates, nulls and no controls", () => {
    render(
      <EvidenceDisplay presentation={rankingPresentation("static_table")} />,
    );
    expect(screen.getByText("62.5%")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Partial result/)).toBeInTheDocument();
    expect(screen.getByText(/1,000 population boards/)).toBeInTheDocument();
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
    expect(screen.queryByLabelText("Rows to show")).not.toBeInTheDocument();
    expect(screen.getByText("Top 4")).toHaveClass("evidence-primary");
  });
  it("sorts, groups, searches, limits rows and resets without requests or mutation", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const presentation = rankingPresentation();
    const original = JSON.stringify(presentation);
    render(<EvidenceDisplay presentation={presentation} />);
    fireEvent.click(screen.getByText("Explore table: sort, search and group"));
    fireEvent.change(screen.getByLabelText("Sort by"), {
      target: { value: "games" },
    });
    expect(
      within(screen.getAllByRole("row")[1]).getByText("15"),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Direction"), {
      target: { value: "desc" },
    });
    expect(
      within(screen.getAllByRole("row")[1]).getByText("125"),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Group by"), {
      target: { value: "unit_name" },
    });
    expect(screen.getByText("Unit: Jinx · 2 rows")).toBeInTheDocument();
    expect(screen.queryByText("140")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Rows to show"), {
      target: { value: "2" },
    });
    expect(screen.getAllByRole("row")).toHaveLength(5);
    expect(screen.getByText(/2 of 3 matching rows shown/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search loaded rows"), {
      target: { value: "Annie" },
    });
    expect(screen.getByText(/1 of 1 matching rows shown/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(screen.getByLabelText("Search loaded rows")).toHaveValue("");
    expect(screen.getByLabelText("Sort by")).toHaveValue("");
    expect(screen.getByLabelText("Group by")).toHaveValue("");
    expect(screen.getByLabelText("Rows to show")).toHaveValue(3);
    expect(JSON.stringify(presentation)).toBe(original);
    expect(fetch).not.toHaveBeenCalled();
    expect(
      visibleRows(
        presentation.bundle.datasets[0],
        presentation.display.columns,
        { search: "", sortBy: "top4_rate", direction: "desc" },
      ).at(-1).key,
    ).toBe("r2");
  });
  it("isolates simultaneous views and reports no search matches", () => {
    render(
      <>
        <EvidenceDisplay
          presentation={rankingPresentation("interactive_table", "one")}
        />
        <EvidenceDisplay
          presentation={rankingPresentation("interactive_table", "two")}
        />
      </>,
    );
    const inputs = screen.getAllByLabelText("Search loaded rows");
    fireEvent.change(inputs[0], { target: { value: "missing" } });
    expect(inputs[1]).toHaveValue("");
    expect(
      screen.getByText("No loaded rows match your search."),
    ).toBeInTheDocument();
  });
  it("shows empty results without invented rows", () => {
    const presentation = rankingPresentation();
    presentation.bundle.datasets[0].rows = [];
    render(<EvidenceDisplay presentation={presentation} />);
    expect(screen.getByText("No reportable results.")).toBeInTheDocument();
  });
  it("renders eight ordered placements with an accessible table", () => {
    render(<EvidenceDisplay presentation={distributionPresentation()} />);
    expect(screen.getByRole("img")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Placement counts"));
    expect(screen.getAllByRole("row")).toHaveLength(9);
    expect(
      within(screen.getAllByRole("row")[1]).getByText("0"),
    ).toBeInTheDocument();
  });
  it("keeps suppression distinct from zero and contains malformed displays", () => {
    const presentation = distributionPresentation();
    presentation.bundle.datasets[0] = {
      ...presentation.bundle.datasets[0],
      unavailable: true,
      bins: [],
      boards: null,
    };
    const { unmount } = render(<EvidenceDisplay presentation={presentation} />);
    expect(
      screen.getByText(/distribution unavailable or suppressed/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    unmount();
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <>
        <p>Preserved answer</p>
        <EvidenceDisplay presentation={{ id: "bad" }} />
      </>,
    );
    expect(screen.getByText("Evidence view unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Preserved answer")).toBeInTheDocument();
  });
});
