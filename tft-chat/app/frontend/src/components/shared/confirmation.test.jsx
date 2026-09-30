import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { useConfirmation } from "./confirmation";

afterEach(cleanup);

/** Exercise the same suspended operation used by specs and composition runs. */
function ConfirmationHarness({ action }) {
  const { confirm, confirmation } = useConfirmation();
  return <>{confirmation}<Button onClick={async () => { if (await confirm("Discard unsaved changes?")) action(); }}>Discard</Button></>;
}

it("focuses Cancel, traps focus, and restores the invoking control after Escape", async () => {
  const action = vi.fn();
  render(<ConfirmationHarness action={action} />);
  const trigger = screen.getByRole("button", { name: "Discard" });
  trigger.focus();
  fireEvent.click(trigger);
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(action).toHaveBeenCalledOnce());
});

it("adapts checkbox boolean events without submitting its surrounding form", () => {
  const submit = vi.fn((event) => event.preventDefault());
  const change = vi.fn();
  render(<form onSubmit={submit}><Checkbox aria-label="Full population" onCheckedChange={change} /></form>);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(change).toHaveBeenCalledWith(true);
  expect(submit).not.toHaveBeenCalled();
});
