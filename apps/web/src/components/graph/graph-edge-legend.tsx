/**
 * US-23: legend entries for how edges are drawn. Shared by whoever adds more
 * edge styles (Aryan's warning icon, US-31): add an entry here rather than a
 * second legend.
 */
export function GraphEdgeLegend({ showAgent, showManual }: { showAgent: boolean; showManual: boolean }) {
  if (!showAgent && !showManual) return null;
  return (
    <ul aria-label="Connection styles" className="flex items-center gap-4 text-xs text-muted">
      {showManual ? (
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="block h-0 w-5 border-t-2 border-solid" style={{ borderColor: "var(--cortex-graph-edge-hub)" }} />
          Manual
        </li>
      ) : null}
      {showAgent ? (
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="block h-0 w-5 border-t-2 border-dashed" style={{ borderColor: "var(--cortex-graph-edge-agent)" }} />
          Auto-detected
        </li>
      ) : null}
    </ul>
  );
}
