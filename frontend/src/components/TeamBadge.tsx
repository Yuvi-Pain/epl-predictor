import type { CSSProperties } from "react";
import { teamHue, teamInitials } from "../lib/teams";

type Size = "sm" | "md" | "lg";

/** Initials on a colour derived from the name. Decorative: always shown next to the name. */
export function TeamBadge({ name, size = "md" }: { name: string; size?: Size }) {
  const style = { "--hue": teamHue(name) } as CSSProperties;
  const sizeClass = size === "md" ? "" : ` badge--${size}`;
  return (
    <span className={`badge${sizeClass}`} style={style} aria-hidden="true">
      {teamInitials(name)}
    </span>
  );
}

export function TeamName({ name, size = "sm" }: { name: string; size?: Size }) {
  return (
    <span className="team">
      <TeamBadge name={name} size={size} />
      <span className="team__name">{name}</span>
    </span>
  );
}
