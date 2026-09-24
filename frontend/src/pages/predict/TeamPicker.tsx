import { useId } from "react";
import type { Team } from "../../api/client";
import { Swap } from "../../components/Icons";

interface Props {
  teams: readonly Team[];
  home: number | null;
  away: number | null;
  onChange: (home: number | null, away: number | null) => void;
}

export function TeamPicker({ teams, home, away, onChange }: Props) {
  const homeId = useId();
  const awayId = useId();
  const parse = (value: string) => (value === "" ? null : Number(value));

  return (
    <div className="picker">
      <TeamSelect
        id={homeId}
        label="Home team"
        teams={teams}
        value={home}
        exclude={away}
        onChange={(v) => onChange(parse(v), away)}
      />
      <button
        type="button"
        className="button button--icon picker__swap"
        onClick={() => onChange(away, home)}
        disabled={home === null && away === null}
        aria-label="Swap home and away"
        title="Swap home and away"
      >
        <Swap width={20} height={20} />
      </button>
      <TeamSelect
        id={awayId}
        label="Away team"
        teams={teams}
        value={away}
        exclude={home}
        onChange={(v) => onChange(home, parse(v))}
      />
    </div>
  );
}

function TeamSelect({
  id,
  label,
  teams,
  value,
  exclude,
  onChange,
}: {
  id: string;
  label: string;
  teams: readonly Team[];
  value: number | null;
  exclude: number | null;
  onChange: (value: string) => void;
}) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="select"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Choose a team…</option>
        {teams
          .filter((t) => t.id !== exclude)
          .map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
      </select>
    </div>
  );
}
