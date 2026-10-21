import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { MarketplacePanel } from "@/components/eaawp/MarketplacePanel";

export const Route = createFileRoute("/marketplace")({
  component: MarketplacePage,
});

function MarketplacePage() {
  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
        <header>
          <h1 className="text-lg font-semibold">Marketplace</h1>
          <p className="text-[12px] text-muted-foreground">Choose which AI employees your company uses. Turning one off blocks its use for everyone; nothing is deleted.</p>
        </header>
        <MarketplacePanel />
      </div>
    </AppShell>
  );
}
