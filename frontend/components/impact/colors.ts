import type { Group } from "@/lib/api";

// Categorical palette for the country groups (distinct in light mode, readable for colour-blind viewers).
export const GROUP_COLOR: Record<Group, string> = {
  MX: "#2459d6",
  AR: "#d9730d",
  CO: "#7c3aed",
  "Rest of SSL": "#0f8a6b",
  "Total SSL": "#475467",
};
