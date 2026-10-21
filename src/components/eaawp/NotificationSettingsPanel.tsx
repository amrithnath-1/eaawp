import { toast } from "sonner";
import { Panel } from "@/components/eaawp/Panel";
import { useNotificationPrefs, useNotificationSettings, useSetNotificationPref, useSetNotificationSettings } from "@/hooks/use-api";
import { useSession } from "@/state/session";
import { cn } from "@/lib/utils";

function Toggle({ on, label, onChange, disabled }: { on: boolean; label: string; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
            className={cn("border px-2 py-0.5 font-mono text-[10px] tracking-[0.12em] disabled:opacity-40",
                          on ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
      {on ? "ON" : "OFF"}
    </button>
  );
}

/** Settings > Notifications: personal choices for everyone; company authorization for administrators. */
export function NotificationSettingsPanel() {
  const { user } = useSession();
  const isAdmin = user?.role === "Company Admin" || user?.role === "AI Administrator";
  const prefs = useNotificationPrefs();
  const setPref = useSetNotificationPref();
  const company = useNotificationSettings(isAdmin);
  const setCompany = useSetNotificationSettings();
  const err = (e: Error) => toast.error(e.message || "Could not save.");
  const companyOn = prefs.data?.company_email_enabled ?? false;

  return (
    <>
      {isAdmin && (
        <Panel title="Company: automatic notification emails" className="lg:col-span-2">
          <p className="text-xs text-muted-foreground">
            Off by default. When you authorize it, people can choose to receive a short email (never the details, only that something needs
            attention, with a link to the app) for the events they select below. Nobody gets email unless <em>both</em> you and they agree.
            Emails go out through the company&apos;s own email connection, at most {company.data?.hourly_cap ?? 50} per hour.
          </p>
          <div className="mt-3 flex items-center gap-3">
            <Toggle on={company.data?.email_enabled ?? false} label="Authorize automatic notification emails for this company"
                    disabled={!company.data || setCompany.isPending || (!company.data.email_enabled && !company.data.email_provider_ready)}
                    onChange={(v) => setCompany.mutate(v, { onError: err, onSuccess: () => toast.success(v ? "Notification emails authorized." : "Notification emails switched off.") })} />
            <span className="text-xs text-muted-foreground" data-testid="company-email-state">
              {company.isLoading ? "Loading…" : company.data?.email_enabled ? "Authorized for this company." : company.data?.email_provider_ready ? "Not authorized." : "Not available: set up and enable the company's email connection in Integrations first."}
            </span>
          </div>
        </Panel>
      )}
      <Panel title="My notifications" className="lg:col-span-2">
        {prefs.isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}
        {prefs.data && prefs.data.categories.length === 0 && (
          <p className="text-xs text-muted-foreground">There are no notification types for your role yet. Administrators are notified about approvals, failed workflows, monitoring alerts and new members.</p>
        )}
        {prefs.data && prefs.data.categories.length > 0 && (
          <>
            {!companyOn && <p className="mb-3 text-xs text-muted-foreground">Email is not authorized for this company, so no emails are sent even if you switch them on. Your choices are saved for when an administrator allows it.</p>}
            <table className="w-full text-left text-[13px]">
              <thead><tr className="label-xs"><th className="py-1 pr-3 font-normal">Event</th><th className="px-3 py-1 font-normal">In the app</th><th className="px-3 py-1 font-normal">By email</th></tr></thead>
              <tbody>
                {prefs.data.categories.map((c) => (
                  <tr key={c.category} className="border-t border-border" data-testid={`pref-${c.category}`}>
                    <td className="py-2 pr-3">{c.label}</td>
                    <td className="px-3 py-2"><Toggle on={c.in_app} label={`${c.label}: show in the app`} disabled={setPref.isPending}
                        onChange={(v) => setPref.mutate({ category: c.category, in_app: v, email: c.email }, { onError: err })} /></td>
                    <td className="px-3 py-2">{c.email_available
                      ? <Toggle on={c.email} label={`${c.label}: send me an email`} disabled={setPref.isPending}
                          onChange={(v) => setPref.mutate({ category: c.category, in_app: c.in_app, email: v }, { onError: err })} />
                      : <span className="text-[11px] text-muted-foreground">Not available</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Panel>
    </>
  );
}
