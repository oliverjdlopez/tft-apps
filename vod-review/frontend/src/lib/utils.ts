import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge conditional classes for the shared shadcn controls. */
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
