import type { ReactNode } from "react";

export const NAV = [
  { id: "overview", href: "/", label: "Overview" },
  { id: "contracts", href: "/contracts/", label: "Contracts" },
  { id: "judges", href: "/judges/", label: "Judge panel" },
  { id: "golden", href: "/golden/", label: "Golden sets" },
  { id: "guide", href: "/guide/", label: "Guide" },
] as const;

export type NavId = (typeof NAV)[number]["id"];

/** The frame every page sits in: the instrument rail on the left, the paper on the right. */
export function Shell({ active, children }: { active: NavId; children: ReactNode }) {
  return (
    <div className="frame">
      <aside className="rail">
        <a className="brand" href="/" aria-label="Seismograph home">
          <b>Seismograph</b>
          <svg width="150" height="18" viewBox="0 0 150 18" aria-hidden="true">
            <polyline
              points="0,9 34,9 40,3 46,15 52,6 58,11 64,9 96,9 101,1 107,17 113,5 119,12 125,9 150,9"
              fill="none"
              stroke="var(--trace)"
              strokeWidth="1.4"
              strokeLinejoin="round"
            />
          </svg>
          <span>process control for AI</span>
        </a>
        <nav className="nav" aria-label="Sections">
          {NAV.map((item) => (
            <a key={item.id} href={item.href} aria-current={item.id === active ? "page" : undefined}>
              {item.label}
            </a>
          ))}
        </nav>
        <div className="rail-foot">
          The model senses.
          <br />
          Code decides.
          <br />
          <a href="/docs">API schema</a> · <a href="https://github.com/nuwansamaranayake/Seismograph">Source</a>
        </div>
      </aside>
      <div className="content">{children}</div>
    </div>
  );
}
