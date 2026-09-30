import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ParameterLabel, { ParameterHelpProvider } from "./ParameterLabel.jsx";
import { parameterHelp } from "./parameterHelp.js";

afterEach(cleanup);

it("opens help only on activation, replaces its content, and restores focus on dismissal", async () => {
  const submit = vi.fn();
  render(
    <ParameterHelpProvider>
      <form onSubmit={submit}>
        <label>
          <ParameterLabel help={parameterHelp.hdbscan.min_cluster_size}>Minimum cluster size</ParameterLabel>
          <input type="checkbox" aria-label="Test control" />
        </label>
        <ParameterLabel help={parameterHelp.hdbscan.min_samples}>Minimum samples</ParameterLabel>
      </form>
    </ParameterHelpProvider>,
  );
  const trigger = screen.getByRole("button", { name: "About Minimum cluster size" });
  fireEvent.mouseOver(trigger);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).not.toHaveAttribute("title");
  fireEvent.click(trigger);
  expect(screen.getByRole("dialog", { name: "Minimum cluster size" })).toHaveTextContent("common structures");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Close parameter help" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "About Minimum samples" }));
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.getByRole("dialog")).toHaveTextContent("more conservative");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "About Minimum samples" })).toHaveFocus());
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "Close parameter help" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(trigger).toHaveFocus());
});

it("provides substantive help for every current algorithm parameter", () => {
  for (const [algorithm, descriptions] of Object.entries(parameterHelp)) {
    const source = readFileSync(resolve(process.cwd(), `../backend/src/domain/compositions/algorithms/${algorithm}/models.py`), "utf8");
    const parameters = source.split(/class Parameters\([^)]*\):/)[1].split(/\nclass |\n    @/)[0];
    const names = [...parameters.matchAll(/^    (\w+):/gm)].map((match) => match[1]);
    expect(Object.keys(descriptions).sort()).toEqual(names.sort());
    for (const description of Object.values(descriptions)) {
      expect(description.length).toBeGreaterThan(100);
      expect(description).not.toMatch(/^Set /);
    }
  }
});
