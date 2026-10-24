import { useRef, type ChangeEventHandler, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

/** Open the existing file importer from a keyboard-accessible shared button. */
export function UploadButton({ onChange, disabled, children }: {
  onChange: ChangeEventHandler<HTMLInputElement>;
  disabled: boolean;
  children: ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  return <>
    <Button type="button" disabled={disabled} onClick={() => input.current?.click()}>{children}</Button>
    <input ref={input} type="file" hidden aria-label="Audio or video file" accept="audio/*,video/*,.mp4,.webm,.mkv,.mov,.mp3,.m4a,.wav,.flac,.ogg,.aac" onChange={onChange} disabled={disabled} />
  </>;
}
