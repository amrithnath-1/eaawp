import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader } from "@/components/eaawp/Panel";
import { roleService } from "@/services";
import type { RoleDefinition } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/roles")({
  head: () => ({
    meta: [
      { title: "User roles & permissions — EAAWP" },
      { name: "description", content: "Create roles and control workspace, AI configuration, approval and document permissions across the company." },
      { property: "og:title", content: "User roles & permissions — EAAWP" },
      { property: "og:description", content: "Permission matrix for company admins, managers, employees and AI administrators." },
    ],
  }),
  component: RolesPage,
});

function RolesPage() {
  const [roles, setRoles] = useState<RoleDefinition[]>(() => roleService.list());
  const permKeys = Object.keys(roles[0]?.permissions ?? {});

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader
          title="Roles & access"
          subtitle="Company Admin defines what each role may see, approve and configure."
          actions={
            <button
              onClick={() =>
                setRoles((r) => [
                  ...r,
                  {
                    name: `Custom Role ${r.length - 3 > 0 ? r.length - 3 : 1}`,
                    system: false,
                    users: 0,
                    permissions: Object.fromEntries(permKeys.map((k) => [k, false])),
                  },
                ])
              }
              className="border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10"
            >
              CREATE ROLE
            </button>
          }
        />

        <div className="mt-4 overflow-x-auto border border-border">
          <table className="w-full min-w-[860px] border-collapse">
            <thead>
              <tr className="bg-surface-2">
                <th className="label-xs border-b border-r border-border px-3 py-2 text-left">Permission</th>
                {roles.map((r) => (
                  <th key={r.name} className="border-b border-r border-border px-3 py-2 text-left last:border-r-0">
                    <div className="text-[13px] font-medium">{r.name}</div>
                    <div className="label-xs mt-0.5">
                      {r.users} users · {r.system ? "SYSTEM" : "CUSTOM"}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {permKeys.map((p) => (
                <tr key={p} className="hover:bg-surface">
                  <td className="border-b border-r border-border px-3 py-2 text-[13px]">{p}</td>
                  {roles.map((r, ri) => (
                    <td key={r.name} className="border-b border-r border-border px-3 py-2 last:border-r-0">
                      <button
                        onClick={() =>
                          setRoles((prev) =>
                            prev.map((x, i) =>
                              i === ri ? { ...x, permissions: { ...x.permissions, [p]: !x.permissions[p] } } : x,
                            ),
                          )
                        }
                        className={cn(
                          "border px-2 py-0.5 font-mono text-[10px] tracking-[0.12em]",
                          r.permissions[p] ? "border-primary text-primary" : "border-border text-muted-foreground",
                        )}
                      >
                        {r.permissions[p] ? "ALLOWED" : "DENIED"}
                      </button>
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td className="label-xs border-r border-border px-3 py-2">Assign users</td>
                {roles.map((r) => (
                  <td key={r.name} className="border-r border-border px-3 py-2 last:border-r-0">
                    <button
                      onClick={() => toast(`Assign users to ${r.name}`)}
                      className="border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-foreground"
                    >
                      MANAGE
                    </button>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
