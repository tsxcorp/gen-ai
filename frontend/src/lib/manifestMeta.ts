import type { ManifestSummary } from "../api/types";
import { isStalePrice } from "./sweep";

export interface ModelWarning {
  level: "warn" | "danger";
  text: string;
}

/** Invariant 9: stale lastVerified (>30d) or deprecated always warns. */
export function modelWarnings(m: Pick<ManifestSummary, "status" | "sunsetDate" | "lastVerified">, now = new Date()): ModelWarning[] {
  const out: ModelWarning[] = [];
  if (m.status === "deprecated") {
    out.push({ level: "danger", text: `Model đã deprecated${m.sunsetDate ? ` (sunset ${m.sunsetDate})` : ""}` });
  } else if (m.sunsetDate) {
    out.push({ level: "warn", text: `Dự kiến ngừng từ ${m.sunsetDate}` });
  }
  if (isStalePrice(m.lastVerified, now)) {
    out.push({
      level: "warn",
      text: m.lastVerified
        ? `Thông số/giá kiểm lần cuối ${m.lastVerified} (> 30 ngày) — có thể đã cũ`
        : "Chưa có lastVerified — thông số/giá có thể đã cũ",
    });
  }
  return out;
}
