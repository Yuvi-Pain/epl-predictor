// Team badges are built from the name alone: initials on a colour picked by
// hashing the name. No crests or league marks, and the same team always gets
// the same colour.

const SKIP = new Set(["fc", "afc", "and", "&", "the"]);

export function teamInitials(name: string): string {
  const words = name
    .replace(/['’.]/g, "")
    .split(/[\s-]+/)
    .filter((w) => w && !SKIP.has(w.toLowerCase()));
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0]!.slice(0, 3).toUpperCase();
  return words
    .slice(0, 2)
    .map((w) => w[0]!)
    .join("")
    .toUpperCase();
}

/** A stable hue (0-359) for a team name. */
export function teamHue(name: string): number {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return hash % 360;
}
