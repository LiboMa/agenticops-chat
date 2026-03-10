export function TokenMetrics({ input, output }: { input: number; output: number }) {
  return (
    <span className="text-xs text-[#666] tabular-nums">
      ↑{input.toLocaleString()} ↓{output.toLocaleString()} Σ{(input + output).toLocaleString()}
    </span>
  );
}
