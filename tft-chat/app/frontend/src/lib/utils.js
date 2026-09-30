import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge conditional classes, resolving Tailwind conflicts for shared UI components. */
export function cn(...inputs) { return twMerge(clsx(inputs)); }
