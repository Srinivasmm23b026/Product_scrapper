import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));
export const money = (value: number | null | undefined) =>
  value == null ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
export const dateTime = (value: string | null | undefined) => (value ? new Date(value).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "Not yet");
export const shortDate = (value: string) => new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
