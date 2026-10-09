import type { ResolveError } from "../api/types";

/** Renders `{key, reason}` errors. Only ever renders `reason` (a string), never the object. */
export function ErrorList({ errors }: { errors: ResolveError[] }) {
  if (errors.length === 0) return null;
  return (
    <ul className="errors" role="alert">
      {errors.map((e, i) => (
        <li key={`${e.key}:${i}`}>{e.reason}</li>
      ))}
    </ul>
  );
}
