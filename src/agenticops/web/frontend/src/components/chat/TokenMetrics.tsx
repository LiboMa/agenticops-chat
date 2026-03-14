export function TokenMetrics({ input, output }: { input: number; output: number }) {
  return (
    <span className="text-xs text-muted-foreground tabular-nums">
      ↑{input.toLocaleString()} ↓{output.toLocaleString()} Σ{(input + output).toLocaleString()}
    </span>
  );
}
