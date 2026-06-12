import type { ReactNode } from "react";

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-7">
      <h1 className="text-[26px] font-semibold tracking-tight text-slate-900">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
    </div>
  );
}

export function Card({
  children,
  className = "",
  pad = true,
}: {
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_-12px_rgba(15,23,42,0.10)] ${
        pad ? "p-6" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 animate-in">
      {message}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-600" />
      {label ?? "Loading…"}
    </div>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  type = "button",
  size = "md",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  type?: "button" | "submit";
  size?: "sm" | "md";
}) {
  const variants = {
    primary:
      "bg-indigo-600 text-white hover:bg-indigo-500 shadow-sm shadow-indigo-600/20",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
    danger: "bg-red-600 text-white hover:bg-red-500",
    ghost: "text-slate-600 hover:bg-slate-100",
  }[variant];
  const sizes = { sm: "px-3 py-1.5 text-xs", md: "px-4 py-2 text-sm" }[size];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${variants} ${sizes}`}
    >
      {children}
    </button>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    slate: "bg-slate-100 text-slate-600 ring-slate-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200",
    red: "bg-red-50 text-red-700 ring-red-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
        tones[tone] ?? tones.slate
      }`}
    >
      {children}
    </span>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      {children}
    </label>
  );
}

export function Select({
  value,
  onChange,
  children,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 ${className}`}
    >
      {children}
    </select>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/60 px-6 py-16 text-center">
      {icon && <div className="mb-3 text-slate-300">{icon}</div>}
      <div className="text-sm font-semibold text-slate-700">{title}</div>
      {body && <div className="mt-1 max-w-sm text-sm text-slate-500">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
