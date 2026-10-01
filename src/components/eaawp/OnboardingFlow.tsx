/**
 * OnboardingFlow — Fresh Company Registration
 *
 * Allows a new company to onboard onto EAAWP.
 * Creates isolated tenant with DMM configuration.
 * Only active in real mode (VITE_USE_REAL_API=true).
 */
import { useState } from "react";
import { Building2, Check, Info, Loader2, User } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import { useOnboardCompany, type OnboardRequest } from "@/hooks/use-api";

interface OnboardingFlowProps {
  onComplete: (companyId: string, companyName: string) => void;
  onCancel: () => void;
}

export function OnboardingFlow({ onComplete, onCancel }: OnboardingFlowProps) {
  const [step, setStep] = useState<"company" | "admin" | "done">("company");
  const [form, setForm] = useState<OnboardRequest>({
    company_name: "",
    industry: "",
    region: "",
    employees: 0,
    website: "",
    description: "",
    admin_name: "",
    admin_email: "",
    admin_password: "",
  });

  const onboard = useOnboardCompany();

  function set(key: keyof OnboardRequest, val: string | number) {
    setForm(f => ({ ...f, [key]: val }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!USE_REAL_API) {
      toast.info("Company creation requires VITE_USE_REAL_API=true.");
      return;
    }
    try {
      const result = await onboard.mutateAsync(form);
      toast.success(`Company "${result.company_name}" created successfully.`);
      setStep("done");
      setTimeout(() => onComplete(result.company_id, result.company_name), 1500);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Onboarding failed.");
    }
  }

  if (step === "done") {
    return (
      <div className="border border-success/30 bg-success/5 p-6 text-center space-y-2">
        <Check className="mx-auto size-8 text-success" strokeWidth={1.5} />
        <p className="font-mono text-[11px] tracking-widest text-success">COMPANY CREATED</p>
        <p className="text-[12px] text-muted-foreground">Setting up your AI workforce…</p>
      </div>
    );
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="border border-border bg-surface p-6 space-y-4 max-w-lg">
      <div className="border-b border-border pb-3">
        <h2 className="text-[15px] font-semibold">Register your company</h2>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Create a new EAAWP tenant with your own isolated AI workforce.
        </p>
      </div>

      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5 text-primary" strokeWidth={1.5} />
          <span><strong>Simulated mode</strong> — set VITE_USE_REAL_API=true to create a real company.</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1.5 border-b border-border pb-3">
        {(["company", "admin"] as const).map(t => (
          <button key={t} type="button" onClick={() => setStep(t)}
            className={cn("flex items-center gap-1.5 border px-3 py-1.5 font-mono text-[10px] tracking-widest",
              step === t ? "border-primary text-primary" : "border-border text-muted-foreground")}>
            {t === "company" ? <Building2 className="size-3" strokeWidth={2} /> : <User className="size-3" strokeWidth={2} />}
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {step === "company" && (
        <div className="space-y-3">
          <div>
            <label className="label-xs">Company name *</label>
            <input required value={form.company_name} onChange={e => set("company_name", e.target.value)}
              placeholder="e.g. Acme Marketing Co."
              className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label-xs">Industry</label>
              <input value={form.industry ?? ""} onChange={e => set("industry", e.target.value)}
                placeholder="e.g. SaaS"
                className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
            </div>
            <div>
              <label className="label-xs">Region</label>
              <input value={form.region ?? ""} onChange={e => set("region", e.target.value)}
                placeholder="e.g. UK · London"
                className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label-xs">Employees</label>
              <input type="number" min={0} value={form.employees ?? 0} onChange={e => set("employees", parseInt(e.target.value) || 0)}
                className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
            </div>
            <div>
              <label className="label-xs">Website</label>
              <input value={form.website ?? ""} onChange={e => set("website", e.target.value)}
                placeholder="https://..."
                className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
            </div>
          </div>
          <div className="flex justify-end pt-2">
            <button type="button" onClick={() => setStep("admin")}
              className="border border-primary px-4 py-1.5 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10">
              NEXT: ADMIN USER →
            </button>
          </div>
        </div>
      )}

      {step === "admin" && (
        <div className="space-y-3">
          <div>
            <label className="label-xs">Your name *</label>
            <input required value={form.admin_name} onChange={e => set("admin_name", e.target.value)}
              placeholder="e.g. Jane Smith"
              className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
          </div>
          <div>
            <label className="label-xs">Work email *</label>
            <input required type="email" value={form.admin_email} onChange={e => set("admin_email", e.target.value)}
              placeholder="jane@yourcompany.com"
              className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
          </div>
          <div>
            <label className="label-xs">Password * (min 8 chars)</label>
            <input required type="password" minLength={8} value={form.admin_password} onChange={e => set("admin_password", e.target.value)}
              className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
          </div>
          <div className="flex gap-2 pt-2">
            <button type="submit" disabled={onboard.isPending || !USE_REAL_API}
              className="flex items-center gap-1.5 border border-primary px-4 py-1.5 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10 disabled:opacity-40">
              {onboard.isPending ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" strokeWidth={2.5} />}
              CREATE COMPANY
            </button>
            <button type="button" onClick={onCancel}
              className="border border-border px-3 py-1.5 font-mono text-[10px] tracking-widest text-muted-foreground hover:text-foreground">
              CANCEL
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
