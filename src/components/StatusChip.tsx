import { chip } from "./ui";

export interface StatusChipProps {
  tone: "ok" | "warn" | "error" | "info";
  label: string;
}

const toneStyles: Record<StatusChipProps["tone"], string> = {
  ok: "border-success/30 bg-success-subtle text-success",
  warn: "border-warning/30 bg-warning-subtle text-warning",
  error: "border-danger/30 bg-danger-subtle text-danger",
  info: "border-info/30 bg-info-subtle text-info",
};

const dotStyles: Record<StatusChipProps["tone"], string> = {
  ok: "bg-success",
  warn: "bg-warning",
  error: "bg-danger",
  info: "bg-info",
};

export default function StatusChip({ tone, label }: StatusChipProps) {
  return (
    <span className={`${chip} ${toneStyles[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dotStyles[tone]}`} />
      {label}
    </span>
  );
}
