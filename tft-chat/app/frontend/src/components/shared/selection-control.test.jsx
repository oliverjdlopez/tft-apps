import React, { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SelectionControl } from "./selection-control";

afterEach(cleanup);

/** Mirror A2UI's controlled selection state without changing its event contract. */
function SelectionHarness({ type, changed }) {
  const [selected, setSelected] = useState(false);
  return <label>Option<SelectionControl type={type} name="fixture" checked={selected} onChange={() => { setSelected(!selected); changed(); }} /></label>;
}

it.each(["radio", "checkbox"])("preserves %s selection semantics and label activation", (type) => {
  const changed = vi.fn();
  render(<SelectionHarness type={type} changed={changed} />);
  fireEvent.click(screen.getByText("Option"));
  expect(screen.getByRole(type)).toBeChecked();
  fireEvent.click(screen.getByRole(type));
  expect(changed).toHaveBeenCalledTimes(type === "radio" ? 1 : 2);
  expect(screen.getByRole(type).getAttribute("aria-checked") ?? String(screen.getByRole(type).checked)).toBe(type === "radio" ? "true" : "false");
});
