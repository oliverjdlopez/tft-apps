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
    <input ref={input} type="file" hidden aria-label="Video file" accept="video/mp4,video/webm,.mp4,.webm" onChange={onChange} disabled={disabled} />
  </>;
}
