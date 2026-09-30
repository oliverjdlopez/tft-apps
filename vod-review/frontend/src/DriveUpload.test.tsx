import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DriveUpload from "./DriveUpload";
import { getDriveConnection, getDriveUpload, uploadRoundsToDrive } from "./api";

vi.mock("./api", () => ({
  connectDriveUrl: "http://localhost:8000/api/gdrive/connect",
  getDriveUpload: vi.fn(),
  getDriveConnection: vi.fn(),
  uploadRoundsToDrive: vi.fn(),
}));

beforeEach(() => { vi.mocked(getDriveConnection).mockResolvedValue({ connected: false }); });

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("Google Drive round uploads", () => {
  it("disables uploading until classification is ready", async () => {
    vi.mocked(getDriveUpload).mockResolvedValue(null);
    render(<DriveUpload videoId="vod" enabled={false} />);
    expect(screen.getByRole("button", { name: "Upload to GDrive" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Connect Google Drive" })).toHaveAttribute("target", "_blank");
    await waitFor(() => expect(getDriveUpload).toHaveBeenCalledWith("vod"));
  });

  it("uploads server-held rounds and shows progress and destination", async () => {
    vi.mocked(getDriveUpload).mockResolvedValue(null);
    vi.mocked(uploadRoundsToDrive).mockResolvedValue({ id: "batch", status: "running", completed: 2, total: 30,
      folder_url: "https://drive.google.com/drive/folders/folder", error: null });
    render(<DriveUpload videoId="vod" enabled />);
    await waitFor(() => expect(getDriveUpload).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Upload to GDrive" }));
    expect(await screen.findByText("Uploading 2/30 clips")).toBeInTheDocument();
    expect(uploadRoundsToDrive).toHaveBeenCalledWith("vod", { key_rounds_only: false, offset_seconds: 0, duration_seconds: 60 });
    expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Open Drive folder" })).toHaveAttribute("href", "https://drive.google.com/drive/folders/folder");
  });

  it("recovers partial failures and allows retry", async () => {
    vi.mocked(getDriveUpload).mockResolvedValue({ id: "batch", status: "failed", completed: 2, total: 3,
      folder_url: null, error: "Google Drive could not be reached." });
    vi.mocked(uploadRoundsToDrive).mockResolvedValue({ id: "batch", status: "completed", completed: 3, total: 3,
      folder_url: null, error: null });
    render(<DriveUpload videoId="vod" enabled />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry GDrive upload" }));
    expect(await screen.findByText("Uploaded 3/3 clips")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows missing authorization without reporting upload success", async () => {
    vi.mocked(getDriveUpload).mockResolvedValue(null);
    vi.mocked(uploadRoundsToDrive).mockRejectedValue(new Error("Connect Google Drive first."));
    render(<DriveUpload videoId="vod" enabled />);
    await waitFor(() => expect(getDriveUpload).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Upload to GDrive" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connect Google Drive first.");
    expect(screen.getByRole("button", { name: "Upload to GDrive" })).toBeEnabled();
  });
});


it("shows that authorization succeeded even when round results are missing", async () => {
  vi.mocked(getDriveConnection).mockResolvedValue({ connected: true });
  vi.mocked(getDriveUpload).mockResolvedValue(null);
  render(<DriveUpload videoId="vod" enabled={false} />);
  expect(await screen.findByText("Google Drive connected")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Upload to GDrive" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Upload to GDrive" })).toHaveAccessibleDescription("Process this video to detect round starts before uploading.");
});

it("refreshes Google connection on returning from login and enables ready results", async () => {
  vi.mocked(getDriveUpload).mockResolvedValue(null);
  const view = render(<DriveUpload videoId="vod" enabled={false} />);
  await waitFor(() => expect(getDriveConnection).toHaveBeenCalledTimes(1));
  vi.mocked(getDriveConnection).mockResolvedValue({ connected: true });
  fireEvent(window, new Event("focus"));
  expect(await screen.findByText("Google Drive connected")).toBeInTheDocument();
  view.rerender(<DriveUpload videoId="vod" enabled />);
  expect(screen.getByRole("button", { name: "Upload to GDrive" })).toBeEnabled();
  expect(screen.queryByText("Process this video to detect round starts before uploading.")).not.toBeInTheDocument();
});

it("sends the round filter, signed offset and duration selected by the user", async () => {
  vi.mocked(getDriveUpload).mockResolvedValue(null);
  vi.mocked(uploadRoundsToDrive).mockResolvedValue({ id: "new", status: "running", completed: 0, total: 3, error: null, folder_url: null });
  render(<DriveUpload videoId="vod" enabled />);
  await waitFor(() => expect(getDriveUpload).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText("Rounds to upload"), { target: { value: "key" } });
  fireEvent.change(screen.getByLabelText("Upload start offset in seconds"), { target: { value: "-5" } });
  fireEvent.change(screen.getByLabelText("Upload clip duration in seconds"), { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "Upload to GDrive" }));
  await waitFor(() => expect(uploadRoundsToDrive).toHaveBeenCalledWith("vod", { key_rounds_only: true, offset_seconds: -5, duration_seconds: 30 }));
  expect(screen.getByLabelText("Upload clip duration in seconds")).toBeDisabled();
});

it("shares the seek offset and rejects invalid clip duration", async () => {
  vi.mocked(getDriveUpload).mockResolvedValue(null);
  const onOffsetChange = vi.fn();
  render(<DriveUpload videoId="vod" enabled offsetSeconds="-8" onOffsetChange={onOffsetChange} />);
  await waitFor(() => expect(getDriveUpload).toHaveBeenCalled());
  expect(screen.getByLabelText("Upload start offset in seconds")).toHaveValue(-8);
  fireEvent.change(screen.getByLabelText("Upload start offset in seconds"), { target: { value: "3" } });
  expect(onOffsetChange).toHaveBeenCalledWith("3");
  fireEvent.change(screen.getByLabelText("Upload clip duration in seconds"), { target: { value: "0" } });
  expect(screen.getByRole("button", { name: "Upload to GDrive" })).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("duration from 1 to 180 seconds");
});
