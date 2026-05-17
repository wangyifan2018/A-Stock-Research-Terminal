"use client";

type DataSourceScanRibbonProps = {
  active: boolean;
};

/** Thin horizontal sweep — suggests AI is pulling underlying market / fundamentals feeds. */
export function DataSourceScanRibbon({ active }: DataSourceScanRibbonProps) {
  if (!active) {
    return null;
  }

  return (
    <div
      className="pointer-events-none absolute inset-x-0 top-0 z-30 h-[2px] overflow-hidden"
      aria-hidden
    >
      <div className="relative h-full w-full bg-gradient-to-r from-transparent via-cyan-400/25 to-transparent">
        <div
          className="absolute -left-1/3 top-0 h-full w-1/3 animate-data-scan-beam bg-gradient-to-r from-transparent via-cyan-200/95 to-transparent shadow-[0_0_14px_rgba(34,211,238,0.65),0_0_28px_rgba(167,243,208,0.25)]"
          style={{ animationDelay: "0.15s" }}
        />
      </div>
    </div>
  );
}
