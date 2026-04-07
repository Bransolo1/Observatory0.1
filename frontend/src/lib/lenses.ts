import {
  GraduationCap,
  Briefcase,
  Palette,
  Brain,
  Stethoscope,
  Users,
  Sigma,
} from "lucide-react";

export interface LensDefinition {
  key: string;
  icon: React.ElementType;
  title: string;
  desc: string;
}

export const LENS_DEFINITIONS: LensDefinition[] = [
  {
    key: "academic",
    icon: GraduationCap,
    title: "Academic",
    desc: "Peer-reviewed research, JTBD, TAM, diffusion theory",
  },
  {
    key: "business",
    icon: Briefcase,
    title: "Business",
    desc: "ROI, LTV/CAC, strategic fit, Porter's forces",
  },
  {
    key: "ux",
    icon: Palette,
    title: "UX",
    desc: "Nielsen heuristics, Baymard benchmarks, WCAG",
  },
  {
    key: "behavioural",
    icon: Brain,
    title: "Behavioural science",
    desc: "Biases, nudges, habit loops (Cialdini, Kahneman, Fogg)",
  },
  {
    key: "clinical",
    icon: Stethoscope,
    title: "Clinical rigour",
    desc: "RCTs, effect sizes, systematic review mindset",
  },
  {
    key: "ethnographic",
    icon: Users,
    title: "Ethnographic",
    desc: "Contextual inquiry, diary studies, lived experience",
  },
  {
    key: "quant",
    icon: Sigma,
    title: "Data science",
    desc: "Causal inference, cohort analysis, significance testing",
  },
];

export const DEFAULT_LENS_WEIGHTS: Record<string, number> = {
  academic: 15,
  business: 20,
  ux: 15,
  behavioural: 15,
  clinical: 10,
  ethnographic: 10,
  quant: 15,
};

/**
 * Set one lens weight and proportionally redistribute the remainder
 * across the other lenses so the total stays at 100.
 */
export function setLensWeight(
  weights: Record<string, number>,
  key: string,
  value: number,
): Record<string, number> {
  const others = Object.keys(weights).filter((k) => k !== key);
  const otherSum = others.reduce((s, k) => s + (weights[k] || 0), 0) || 1;
  const remainder = Math.max(0, 100 - value);
  const next: Record<string, number> = { ...weights, [key]: value };
  let running = value;
  others.forEach((k, i) => {
    if (i === others.length - 1) {
      next[k] = Math.max(0, 100 - running);
    } else {
      const share = Math.round(((weights[k] || 0) / otherSum) * remainder);
      next[k] = share;
      running += share;
    }
  });
  return next;
}

/** Merge incoming weights with defaults so new lens keys always exist. */
export function mergeLensWeights(
  incoming: Record<string, number> | undefined | null,
): Record<string, number> {
  const merged: Record<string, number> = { ...DEFAULT_LENS_WEIGHTS };
  if (incoming) {
    for (const [k, v] of Object.entries(incoming)) {
      if (typeof v === "number") merged[k] = v;
    }
  }
  return merged;
}
