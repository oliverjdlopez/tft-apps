import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Modal } from "./modal";
import { UploadButton } from "./upload-button";
import { Button } from "../ui/button";

afterEach(cleanup);

/** Exercise the conditional mounting used by the replay settings dialog. */
function DialogHarness() {
  const [open, setOpen] = useState(false);
  return <><Button onClick={() => setOpen(true)}>Settings</Button>{open && <Modal title="Settings" onOpenChange={setOpen}><Button onClick={() => setOpen(false)}>Cancel</Button></Modal>}</>;
}

it("closes a conditional dialog with Escape and restores focus", async () => {
  render(<DialogHarness />);
  const trigger = screen.getByRole("button", { name: "Settings" });
  trigger.focus();
  fireEvent.click(trigger);
  expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("forwards the original file event and disables both upload entry points while busy", () => {
  const change = vi.fn();
  const { rerender } = render(<UploadButton onChange={change} disabled={false}>Upload video</UploadButton>);
  const file = new File(["fixture"], "fixture.mp4", { type: "video/mp4" });
  fireEvent.change(screen.getByLabelText("Video file"), { target: { files: [file] } });
  expect(change).toHaveBeenCalledOnce();
  expect(change.mock.calls[0][0].target.files[0]).toBe(file);
  rerender(<UploadButton onChange={change} disabled>Uploading…</UploadButton>);
  expect(screen.getByRole("button")).toBeDisabled();
  expect(screen.getByLabelText("Video file")).toBeDisabled();
});
