interface ProviderIconProps {
  provider: string;
  className?: string;
}

const PROVIDER_STYLES: Record<string, { bg: string; label: string }> = {
  claude_code: { bg: "bg-orange-500/20 text-orange-400", label: "C" },
  codex: { bg: "bg-cyan-500/20 text-cyan-400", label: "O" },
  kimi: { bg: "bg-purple-500/20 text-purple-400", label: "K" },
  vibe: { bg: "bg-pink-500/20 text-pink-400", label: "V" },
  agy: { bg: "bg-indigo-500/20 text-indigo-400", label: "A" },
  aider: { bg: "bg-emerald-500/20 text-emerald-400", label: "Ai" },
};

export function ProviderIcon({ provider, className = "" }: ProviderIconProps) {
  const p = PROVIDER_STYLES[provider?.toLowerCase()] || { bg: "bg-slate-500/20 text-slate-400", label: "?" };
  return (
    <span
      className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${p.bg} ${className}`}
      title={provider}
    >
      {p.label}
    </span>
  );
}
