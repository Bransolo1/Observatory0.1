"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { onboarding as onboardingApi, productAreas, competitors, dataSources } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  FlaskConical,
  Telescope,
  Target,
  Database,
  Sparkles,
  CheckCircle2,
  Plus,
  X,
  ArrowRight,
  ArrowLeft,
} from "lucide-react";
import { LENS_DEFINITIONS, DEFAULT_LENS_WEIGHTS, setLensWeight as calcLensWeight } from "@/lib/lenses";
import { DATA_SOURCE_CATALOG, DATA_SOURCE_TYPE_LABEL } from "@/lib/data-sources";

const TOTAL_STEPS = 6;

const SUGGESTED_AREAS = [
  "Onboarding", "Activation", "Dashboard", "Search",
  "Checkout", "Billing", "Integrations", "Reporting",
  "Admin", "Mobile", "Notifications", "Settings",
];


export default function WelcomePage() {
  const router = useRouter();
  const { currentOrg, isLoading, isAuthenticated, refresh } = useAuth();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);

  // Step 2: product
  const [productDescription, setProductDescription] = useState("");
  const [areas, setAreas] = useState<{ name: string }[]>([]);
  const [areaInput, setAreaInput] = useState("");
  const [savedSteps, setSavedSteps] = useState<Set<number>>(new Set());

  // Step 3: competitors
  const [comps, setComps] = useState<{ name: string; website_url: string }[]>([]);
  const [compName, setCompName] = useState("");
  const [compUrl, setCompUrl] = useState("");

  // Step 4: data sources (selections only — stored as 'planned')
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set());

  // Step 5: lens weights
  const [lenses, setLenses] = useState<Record<string, number>>({ ...DEFAULT_LENS_WEIGHTS });

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace("/login");
  }, [isLoading, isAuthenticated, router]);

  useEffect(() => {
    if (currentOrg?.is_onboarded) router.replace("/overview");
  }, [currentOrg, router]);

  if (isLoading || !currentOrg) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  const orgId = currentOrg.id;

  const addArea = (name: string) => {
    const trimmed = name.trim();
    if (!trimmed || areas.find((a) => a.name.toLowerCase() === trimmed.toLowerCase())) return;
    setAreas([...areas, { name: trimmed }]);
    setAreaInput("");
  };

  const addCompetitor = () => {
    if (!compName.trim()) return;
    setComps([...comps, { name: compName.trim(), website_url: compUrl.trim() }]);
    setCompName("");
    setCompUrl("");
  };

  const toggleSource = (type: string, name: string) => {
    const key = `${type}::${name}`;
    const next = new Set(selectedSources);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelectedSources(next);
  };

  const handleLensWeight = (key: string, value: number) => {
    setLenses(calcLensWeight(lenses, key, value));
  };

  const saveStepData = async (nextStep: number) => {
    setSaving(true);
    try {
      if (step === 1) {
        // Save product description + areas (only create areas once)
        await onboardingApi.update(orgId, { product_description: productDescription, step: nextStep });
        if (!savedSteps.has(1)) {
          await Promise.all(areas.map((a) => productAreas.create(orgId, { name: a.name })));
        }
      } else if (step === 2) {
        if (!savedSteps.has(2)) {
          await Promise.all(
            comps.map((c) =>
              competitors.create(orgId, {
                name: c.name,
                website_url: c.website_url || undefined,
              })
            )
          );
        }
        await onboardingApi.update(orgId, { step: nextStep });
      } else if (step === 3) {
        if (!savedSteps.has(3)) {
          await Promise.all(
            Array.from(selectedSources).map((key) => {
              const [source_type, name] = key.split("::");
              return dataSources.create(orgId, { source_type, name });
            })
          );
        }
        await onboardingApi.update(orgId, { step: nextStep });
      } else if (step === 4) {
        await onboardingApi.update(orgId, { lens_weights: lenses, step: nextStep });
      } else {
        await onboardingApi.update(orgId, { step: nextStep });
      }
    } finally {
      setSaving(false);
    }
  };

  const next = async () => {
    await saveStepData(step + 1);
    setSavedSteps((prev) => new Set(prev).add(step));
    setStep(step + 1);
  };

  const back = () => setStep(Math.max(0, step - 1));

  const finish = async () => {
    setSaving(true);
    try {
      await onboardingApi.update(orgId, { is_onboarded: true, step: TOTAL_STEPS });
      await refresh();
      router.push("/overview");
    } finally {
      setSaving(false);
    }
  };

  const canAdvance = () => {
    if (step === 1) return productDescription.trim().length > 0 && areas.length >= 1;
    if (step === 2) return comps.length >= 1;
    if (step === 3) return selectedSources.size >= 1;
    return true;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-zinc-50 to-white dark:from-zinc-950 dark:to-zinc-900">
      {/* Header */}
      <header className="border-b border-zinc-200/60 dark:border-zinc-800 bg-white/70 dark:bg-zinc-950/70 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5" />
            <span className="font-bold tracking-tight">Observatory</span>
          </div>
          <div className="text-sm text-muted-foreground">
            Step {Math.min(step + 1, TOTAL_STEPS)} of {TOTAL_STEPS}
          </div>
        </div>
        {/* Progress bar */}
        <div className="h-1 bg-zinc-100 dark:bg-zinc-800">
          <div
            className="h-full bg-zinc-900 dark:bg-white transition-all duration-300"
            style={{ width: `${((step + 1) / TOTAL_STEPS) * 100}%` }}
          />
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-12">
        {step === 0 && <StepWelcome />}
        {step === 1 && (
          <StepProduct
            description={productDescription}
            setDescription={setProductDescription}
            areas={areas}
            setAreas={setAreas}
            areaInput={areaInput}
            setAreaInput={setAreaInput}
            addArea={addArea}
            orgName={currentOrg.name}
          />
        )}
        {step === 2 && (
          <StepCompetitors
            comps={comps}
            setComps={setComps}
            compName={compName}
            setCompName={setCompName}
            compUrl={compUrl}
            setCompUrl={setCompUrl}
            addCompetitor={addCompetitor}
          />
        )}
        {step === 3 && (
          <StepDataSources
            selected={selectedSources}
            toggle={toggleSource}
          />
        )}
        {step === 4 && <StepLenses lenses={lenses} setLensWeight={handleLensWeight} />}
        {step === 5 && (
          <StepSummary
            productDescription={productDescription}
            areas={areas}
            comps={comps}
            sources={selectedSources}
            lenses={lenses}
          />
        )}

        {/* Footer nav */}
        <div className="mt-12 flex items-center justify-between">
          {step > 0 ? (
            <Button variant="ghost" onClick={back} disabled={saving}>
              <ArrowLeft className="h-4 w-4 mr-2" /> Back
            </Button>
          ) : (
            <div />
          )}

          {step < TOTAL_STEPS - 1 ? (
            <Button onClick={next} disabled={!canAdvance() || saving} className="h-11 px-6">
              {saving ? "Saving..." : "Continue"}
              <ArrowRight className="h-4 w-4 ml-2" />
            </Button>
          ) : (
            <Button onClick={finish} disabled={saving} className="h-11 px-6">
              {saving ? "Finishing..." : "Enter Observatory"}
              <ArrowRight className="h-4 w-4 ml-2" />
            </Button>
          )}
        </div>
      </main>
    </div>
  );
}

// ─── Step 0: Welcome ─────────────────────────────────────────────────────────
function StepWelcome() {
  return (
    <div className="space-y-8">
      <div>
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-100 dark:bg-zinc-800 text-xs font-medium mb-4">
          <Sparkles className="h-3 w-3" /> Welcome to Observatory
        </div>
        <h1 className="text-4xl font-bold tracking-tight mb-3">
          Turn scattered signals into decisions your team can act on.
        </h1>
        <p className="text-lg text-muted-foreground leading-relaxed">
          Observatory synthesizes intelligence from multiple input layers, filters it through seven
          expert analytical lenses, and surfaces the priorities that will move your product forward.
        </p>
      </div>

      <div className="grid gap-3">
        <ValueRow icon={Telescope} title="Intelligence Layers">
          Market signals, clickstream, telemetry, voice of customer, social listening, academic corpora, and more — unified in one place.
        </ValueRow>
        <ValueRow icon={Target} title="7 Expert Lenses">
          Every insight evaluated through academic, business, UX, behavioural science, clinical rigour, ethnographic, and data science perspectives.
        </ValueRow>
        <ValueRow icon={CheckCircle2} title="Actionable Priorities">
          Ranked experiment recommendations, friction reports, and competitive battlecards — not another dashboard to ignore.
        </ValueRow>
      </div>

      <div className="p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50">
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">This setup takes 3 minutes.</span> We&apos;ll
          ask about your product, competitors, and how you&apos;d like Observatory to weigh evidence.
          You can change anything later in Settings.
        </p>
      </div>
    </div>
  );
}

function ValueRow({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4 p-4 rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="shrink-0 w-10 h-10 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 flex items-center justify-center">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div className="font-semibold mb-1">{title}</div>
        <div className="text-sm text-muted-foreground">{children}</div>
      </div>
    </div>
  );
}

// ─── Step 1: Product ─────────────────────────────────────────────────────────
function StepProduct({
  description, setDescription, areas, setAreas, areaInput, setAreaInput, addArea, orgName,
}: {
  description: string; setDescription: (s: string) => void;
  areas: { name: string }[]; setAreas: (a: { name: string }[]) => void;
  areaInput: string; setAreaInput: (s: string) => void;
  addArea: (name: string) => void; orgName: string;
}) {
  const removeArea = (name: string) => setAreas(areas.filter((a) => a.name !== name));
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight mb-2">Tell us about {orgName}</h1>
        <p className="text-muted-foreground">
          This helps Observatory tailor analysis to your product context and domain.
        </p>
      </div>

      <div className="space-y-3">
        <Label htmlFor="product">What does your product do?</Label>
        <textarea
          id="product"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="A short description — e.g. 'B2B SaaS platform for HR teams to manage employee performance reviews and 360-feedback cycles'"
          rows={3}
          className="w-full px-3 py-2 text-sm border rounded-md bg-transparent border-input focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <p className="text-xs text-muted-foreground">
          {description.trim().length === 0
            ? "At least a sentence or two"
            : "Looks good"}
        </p>
      </div>

      <div className="space-y-3">
        <div>
          <Label>Product areas</Label>
          <p className="text-sm text-muted-foreground mt-1">
            The major functional areas Observatory should track friction and priorities for. Add 2-6.
          </p>
        </div>

        {areas.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {areas.map((a) => (
              <div key={a.name} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 text-sm">
                {a.name}
                <button onClick={() => removeArea(a.name)} className="hover:opacity-70">
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <Input
            value={areaInput}
            onChange={(e) => setAreaInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addArea(areaInput); } }}
            placeholder="e.g. Onboarding"
            className="h-10"
          />
          <Button type="button" onClick={() => addArea(areaInput)} variant="outline" disabled={!areaInput.trim()}>
            <Plus className="h-4 w-4 mr-1" /> Add
          </Button>
        </div>

        <div>
          <p className="text-xs text-muted-foreground mb-2">Or pick from common areas:</p>
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTED_AREAS.filter((s) => !areas.find((a) => a.name === s)).map((s) => (
              <button
                key={s}
                onClick={() => addArea(s)}
                className="px-2.5 py-1 rounded-full border border-zinc-200 dark:border-zinc-800 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              >
                + {s}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Step 2: Competitors ─────────────────────────────────────────────────────
function StepCompetitors({
  comps, setComps, compName, setCompName, compUrl, setCompUrl, addCompetitor,
}: {
  comps: { name: string; website_url: string }[];
  setComps: (c: { name: string; website_url: string }[]) => void;
  compName: string; setCompName: (s: string) => void;
  compUrl: string; setCompUrl: (s: string) => void;
  addCompetitor: () => void;
}) {
  const remove = (name: string) => setComps(comps.filter((c) => c.name !== name));
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight mb-2">Who are you competing with?</h1>
        <p className="text-muted-foreground">
          Observatory will monitor their pricing, feature launches, messaging, and market moves —
          and surface what matters through weekly digests and on-demand battlecards.
        </p>
      </div>

      {comps.length > 0 && (
        <div className="space-y-2">
          {comps.map((c) => (
            <div key={c.name} className="flex items-center justify-between p-3 rounded-lg border border-zinc-200 dark:border-zinc-800">
              <div>
                <div className="font-medium">{c.name}</div>
                {c.website_url && <div className="text-xs text-muted-foreground">{c.website_url}</div>}
              </div>
              <button onClick={() => remove(c.name)} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cname" className="text-xs">Competitor name</Label>
            <Input id="cname" value={compName} onChange={(e) => setCompName(e.target.value)} placeholder="e.g. Lattice" className="h-10" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="curl" className="text-xs">Website (optional)</Label>
            <Input id="curl" value={compUrl} onChange={(e) => setCompUrl(e.target.value)} placeholder="https://lattice.com" className="h-10" />
          </div>
        </div>
        <Button type="button" onClick={addCompetitor} variant="outline" disabled={!compName.trim()} className="w-full">
          <Plus className="h-4 w-4 mr-1" /> Add competitor
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        Start with 3-5 direct competitors. You can add more later — and Observatory will also
        surface adjacent players as it scans the market.
      </p>
    </div>
  );
}

// ─── Step 3: Data Sources ────────────────────────────────────────────────────
function StepDataSources({ selected, toggle }: { selected: Set<string>; toggle: (t: string, n: string) => void }) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight mb-2">Which signals should we watch?</h1>
        <p className="text-muted-foreground">
          Select the sources you want Observatory to ingest. You don&apos;t need to connect them
          now — we&apos;ll guide you through integrations after setup.
        </p>
      </div>

      <div className="space-y-6">
        {DATA_SOURCE_CATALOG.map((cat) => (
          <div key={cat.type}>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-1 h-4 bg-zinc-900 dark:bg-white rounded-full" />
              <h3 className="font-semibold text-sm uppercase tracking-wide">{DATA_SOURCE_TYPE_LABEL[cat.type]}</h3>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {cat.items.map((item) => {
                const key = `${cat.type}::${item.name}`;
                const isSelected = selected.has(key);
                return (
                  <button
                    key={item.name}
                    onClick={() => toggle(cat.type, item.name)}
                    className={`text-left p-3 rounded-lg border transition-all ${
                      isSelected
                        ? "border-zinc-900 dark:border-white bg-zinc-50 dark:bg-zinc-900"
                        : "border-zinc-200 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-medium text-sm">{item.name}</div>
                        <div className="text-xs text-muted-foreground">{item.desc}</div>
                      </div>
                      {isSelected && <CheckCircle2 className="h-4 w-4 text-zinc-900 dark:text-white" />}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Step 4: Analytical Lenses ───────────────────────────────────────────────
function StepLenses({
  lenses, setLensWeight,
}: {
  lenses: Record<string, number>;
  setLensWeight: (k: string, v: number) => void;
}) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight mb-2">How should we weigh evidence?</h1>
        <p className="text-muted-foreground">
          Every Observatory insight is evaluated through {LENS_DEFINITIONS.length} expert analytical
          lenses. Tell us which perspectives matter most for your team&apos;s decisions.
        </p>
      </div>

      <div className="space-y-4">
        {LENS_DEFINITIONS.map((lens) => (
          <LensSlider
            key={lens.key}
            icon={lens.icon}
            title={lens.title}
            description={lens.desc}
            value={lenses[lens.key] || 0}
            onChange={(v) => setLensWeight(lens.key, v)}
          />
        ))}
      </div>

      <div className="p-3 rounded-lg bg-zinc-50 dark:bg-zinc-900 text-xs text-muted-foreground">
        Weights sum to 100. Most teams start at roughly equal weighting and adjust as they calibrate.
      </div>
    </div>
  );
}

function LensSlider({
  icon: Icon, title, description, value, onChange,
}: {
  icon: React.ElementType; title: string; description: string; value: number; onChange: (v: number) => void;
}) {
  return (
    <div className="p-4 rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center shrink-0">
            <Icon className="h-4 w-4" />
          </div>
          <div>
            <div className="font-semibold text-sm">{title}</div>
            <div className="text-xs text-muted-foreground">{description}</div>
          </div>
        </div>
        <div className="text-2xl font-bold tabular-nums">{value}</div>
      </div>
      <input
        type="range"
        min="10"
        max="80"
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value))}
        className="w-full accent-zinc-900 dark:accent-white"
      />
    </div>
  );
}

// ─── Step 5: Summary ─────────────────────────────────────────────────────────
function StepSummary({
  productDescription, areas, comps, sources, lenses,
}: {
  productDescription: string;
  areas: { name: string }[];
  comps: { name: string; website_url: string }[];
  sources: Set<string>;
  lenses: Record<string, number>;
}) {
  return (
    <div className="space-y-8">
      <div>
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-900 text-xs font-medium text-green-700 dark:text-green-400 mb-4">
          <CheckCircle2 className="h-3 w-3" /> Setup complete
        </div>
        <h1 className="text-3xl font-bold tracking-tight mb-2">You&apos;re ready to start.</h1>
        <p className="text-muted-foreground">
          Observatory will begin analyzing your configured signals. Here&apos;s a summary of what you&apos;ve set up:
        </p>
      </div>

      <div className="space-y-4">
        <SummaryRow label="Product" value={productDescription || "—"} />
        <SummaryRow
          label={`Product areas (${areas.length})`}
          value={areas.map((a) => a.name).join(" · ")}
        />
        <SummaryRow
          label={`Competitors (${comps.length})`}
          value={comps.map((c) => c.name).join(" · ")}
        />
        <SummaryRow
          label={`Data sources (${sources.size})`}
          value={Array.from(sources).map((s) => s.split("::")[1]).join(" · ")}
        />
        <SummaryRow
          label="Lens weights"
          value={LENS_DEFINITIONS.map((l) => `${l.title} ${lenses[l.key] || 0}`).join(" · ")}
        />
      </div>

      <div className="p-4 rounded-lg border-2 border-zinc-900 dark:border-white bg-zinc-900 text-white dark:bg-white dark:text-zinc-900">
        <div className="font-semibold mb-1">What happens next?</div>
        <ul className="text-sm space-y-1 opacity-80">
          <li>→ Observatory will start scanning your competitors and market signals</li>
          <li>→ Connect your data sources from Settings → Integrations when ready</li>
          <li>→ Upload research to the Knowledge Base to enrich analysis</li>
          <li>→ First insights typically surface within hours of data flowing in</li>
        </ul>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-4 py-3 border-b border-zinc-200 dark:border-zinc-800">
      <div className="w-48 shrink-0 text-sm font-medium text-muted-foreground">{label}</div>
      <div className="text-sm flex-1">{value || <span className="text-muted-foreground">—</span>}</div>
    </div>
  );
}
