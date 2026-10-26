/**
 * The approved company profile: facts every AI employee is told about the company. Administrators edit it; everyone
 * else can read what the AI employees are told. Nothing is pre-filled by guesswork; empty fields are left out.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Panel } from "@/components/eaawp/Panel";
import {
  useCompanyProfile,
  useSaveCompanyProfile,
  type CompanyProfile,
  type ServiceEntry,
} from "@/hooks/use-conversations";
import { apiErrorMessage } from "@/lib/api-client";

const EMPTY: CompanyProfile = {
  brand_name: "",
  legal_or_long_name: "",
  tagline: "",
  website: "",
  summary: "",
  location_and_service_area: "",
  services: [],
  target_audiences: [],
  brand_voice: "",
  approved_claims: [],
  forbidden_claims: [],
  marketing_objectives: [],
  kpis: [],
  policies: "",
};

const field =
  "mt-1 w-full border border-input bg-background px-2.5 py-1.5 text-[12px] outline-none focus:border-ring disabled:opacity-70";

function Labeled({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-[12px]">
      <span className="text-foreground">{label}</span>
      {hint && <span className="ml-1 text-[11px] text-muted-foreground">{hint}</span>}
      {children}
    </label>
  );
}

function ListField({
  label,
  hint,
  value,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  value: string[];
  onChange: (v: string[]) => void;
  disabled: boolean;
}) {
  return (
    <Labeled label={label} hint={hint ?? "one per line"}>
      <textarea
        rows={3}
        disabled={disabled}
        value={value.join("\n")}
        onChange={(e) =>
          onChange(
            e.target.value
              .split("\n")
              .map((x) => x.trimStart())
              .filter((x, i, a) => x || i === a.length - 1),
          )
        }
        onBlur={(e) =>
          onChange(
            e.target.value
              .split("\n")
              .map((x) => x.trim())
              .filter(Boolean),
          )
        }
        className={field}
      />
    </Labeled>
  );
}

export function CompanyProfilePanel({ canEdit }: { canEdit: boolean }) {
  const { data, isLoading, isError, error } = useCompanyProfile();
  const save = useSaveCompanyProfile();
  const [p, setP] = useState<CompanyProfile>(EMPTY);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data && !dirty) setP({ ...EMPTY, ...data.profile });
  }, [data, dirty]);

  function set<K extends keyof CompanyProfile>(k: K, v: CompanyProfile[K]) {
    setP((cur) => ({ ...cur, [k]: v }));
    setDirty(true);
  }
  function setService(i: number, patch: Partial<ServiceEntry>) {
    set(
      "services",
      p.services.map((s, j) => (j === i ? { ...s, ...patch } : s)),
    );
  }

  if (isLoading)
    return (
      <Panel title="Approved company profile" className="lg:col-span-2">
        <p className="text-[12px] text-muted-foreground">
          <Loader2 className="inline size-3 animate-spin" /> Loading…
        </p>
      </Panel>
    );
  if (isError)
    return (
      <Panel title="Approved company profile" className="lg:col-span-2">
        <p className="text-[12px] text-destructive">
          Could not load the profile: {apiErrorMessage(error)}
        </p>
      </Panel>
    );

  const ro = !canEdit;
  return (
    <Panel title="Approved company profile" className="lg:col-span-2">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          const services = p.services.filter((s) => s.name.trim());
          save.mutate(
            { ...p, services },
            {
              onSuccess: () => {
                setDirty(false);
                toast.success("Company profile saved. AI employees use it from the next message.");
              },
              onError: (err) => toast.error(apiErrorMessage(err)),
            },
          );
        }}
      >
        <p className="text-[12px] text-muted-foreground">
          Every AI employee is given these facts as reference data and told not to go beyond them.
          Enter only verified, approved information (for example from your own website). Leave a
          field empty rather than guessing.
          {ro && " Only company administrators can change it."}
          {data?.updated_at &&
            ` Last updated ${new Date(data.updated_at.endsWith("Z") || data.updated_at.includes("+") ? data.updated_at : `${data.updated_at}Z`).toLocaleString()}.`}
        </p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Labeled label="Brand name">
            <input
              disabled={ro}
              value={p.brand_name}
              onChange={(e) => set("brand_name", e.target.value)}
              maxLength={200}
              className={field}
            />
          </Labeled>
          <Labeled label="Full / legal name">
            <input
              disabled={ro}
              value={p.legal_or_long_name}
              onChange={(e) => set("legal_or_long_name", e.target.value)}
              maxLength={200}
              className={field}
            />
          </Labeled>
          <Labeled label="Tagline">
            <input
              disabled={ro}
              value={p.tagline}
              onChange={(e) => set("tagline", e.target.value)}
              maxLength={300}
              className={field}
            />
          </Labeled>
          <Labeled label="Website">
            <input
              disabled={ro}
              value={p.website}
              onChange={(e) => set("website", e.target.value)}
              maxLength={300}
              placeholder="https://"
              className={field}
            />
          </Labeled>
        </div>
        <Labeled label="About the company">
          <textarea
            disabled={ro}
            rows={3}
            value={p.summary}
            onChange={(e) => set("summary", e.target.value)}
            maxLength={2000}
            className={field}
          />
        </Labeled>
        <Labeled label="Location and service area">
          <input
            disabled={ro}
            value={p.location_and_service_area}
            onChange={(e) => set("location_and_service_area", e.target.value)}
            maxLength={1000}
            className={field}
          />
        </Labeled>

        <fieldset className="space-y-2 border border-border p-3">
          <legend className="px-1 text-[12px]">Services</legend>
          {p.services.length === 0 && (
            <p className="text-[11px] text-muted-foreground">No services entered yet.</p>
          )}
          {p.services.map((s, i) => (
            <div
              key={i}
              className="grid grid-cols-1 gap-2 border-b border-border pb-2 last:border-0 md:grid-cols-[1fr_2fr_1fr_auto]"
            >
              <input
                disabled={ro}
                aria-label={`Service ${i + 1} name`}
                placeholder="Service name"
                value={s.name}
                onChange={(e) => setService(i, { name: e.target.value })}
                maxLength={200}
                className={field}
              />
              <input
                disabled={ro}
                aria-label={`Service ${i + 1} description`}
                placeholder="What it is"
                value={s.description}
                onChange={(e) => setService(i, { description: e.target.value })}
                maxLength={1000}
                className={field}
              />
              <input
                disabled={ro}
                aria-label={`Service ${i + 1} audience`}
                placeholder="Who it is for"
                value={s.audience}
                onChange={(e) => setService(i, { audience: e.target.value })}
                maxLength={500}
                className={field}
              />
              {!ro && (
                <button
                  type="button"
                  aria-label={`Remove service ${i + 1}`}
                  onClick={() =>
                    set(
                      "services",
                      p.services.filter((_, j) => j !== i),
                    )
                  }
                  className="mt-1 grid size-8 place-items-center border border-border hover:bg-foreground/5"
                >
                  <Trash2 className="size-3" />
                </button>
              )}
            </div>
          ))}
          {!ro && (
            <button
              type="button"
              onClick={() =>
                set("services", [...p.services, { name: "", description: "", audience: "" }])
              }
              className="inline-flex items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] hover:bg-foreground/5"
            >
              <Plus className="size-3" /> ADD SERVICE
            </button>
          )}
        </fieldset>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <ListField
            label="Target audiences"
            value={p.target_audiences}
            onChange={(v) => set("target_audiences", v)}
            disabled={ro}
          />
          <ListField
            label="Marketing objectives"
            value={p.marketing_objectives}
            onChange={(v) => set("marketing_objectives", v)}
            disabled={ro}
          />
          <ListField label="KPIs" value={p.kpis} onChange={(v) => set("kpis", v)} disabled={ro} />
          <ListField
            label="Approved claims"
            hint="statements that may be used"
            value={p.approved_claims}
            onChange={(v) => set("approved_claims", v)}
            disabled={ro}
          />
          <ListField
            label="Forbidden claims"
            hint="never state or imply"
            value={p.forbidden_claims}
            onChange={(v) => set("forbidden_claims", v)}
            disabled={ro}
          />
        </div>
        <Labeled label="Brand voice">
          <textarea
            disabled={ro}
            rows={2}
            value={p.brand_voice}
            onChange={(e) => set("brand_voice", e.target.value)}
            maxLength={2000}
            className={field}
          />
        </Labeled>
        <Labeled label="Company policies the AI must follow">
          <textarea
            disabled={ro}
            rows={2}
            value={p.policies}
            onChange={(e) => set("policies", e.target.value)}
            maxLength={2000}
            className={field}
          />
        </Labeled>

        {!ro && (
          <button
            type="submit"
            disabled={save.isPending || !dirty}
            className="inline-flex h-9 items-center gap-2 border border-primary bg-primary px-3 font-mono text-[10px] tracking-widest text-primary-foreground disabled:opacity-50"
          >
            {save.isPending && <Loader2 className="size-3 animate-spin" />}{" "}
            {dirty ? "SAVE PROFILE" : "SAVED"}
          </button>
        )}
      </form>
    </Panel>
  );
}
