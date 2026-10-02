import type { ComponentType } from "react";
import Link from "next/link";

import { CortexMark } from "@/components/brand/cortex-mark";

import { ChevronLeftIcon } from "./sidebar-icons";

export type SidebarIcon = ComponentType<{ className?: string }>;

export type SidebarLink = {
  label: string;
  href: string;
  icon: SidebarIcon;
  badge?: number;
  exact?: boolean;
};

export type SidebarConversation = {
  id: string;
  label: string;
  href: string;
};

type AppSidebarProps = {
  productLabel: string;
  workspace: { label: string; href: string };
  account: { label: string; detail: string; href: string };
  activePath: string;
  primaryLinks: SidebarLink[];
  secondaryLinks?: SidebarLink[];
  utilityLinks?: SidebarLink[];
  recentConversations?: SidebarConversation[];
};

function isActiveLink(link: SidebarLink, activePath: string) {
  return link.exact
    ? activePath === link.href
    : activePath === link.href || activePath.startsWith(`${link.href}/`);
}

function accountInitials(label: string) {
  const parts = label
    .replace(/@.*$/, "")
    .split(/[\s._-]+/)
    .filter(Boolean);

  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "A";
}

function SidebarNavigation({
  label,
  links,
  activePath,
}: {
  label: string;
  links: SidebarLink[];
  activePath: string;
}) {
  return (
    <nav aria-label={label} className="space-y-1">
      {links.map((link) => {
        const isActive = isActiveLink(link, activePath);
        const Icon = link.icon;

        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={isActive ? "page" : undefined}
            className="group relative flex min-h-10 items-center gap-3 rounded-[var(--cortex-sidebar-item-radius)] px-3 text-sm font-medium text-[var(--cortex-sidebar-text)] transition-[background,color,box-shadow] duration-150 ease-out hover:bg-[var(--cortex-sidebar-hover)] hover:text-foreground active:bg-[var(--cortex-sidebar-hover)] aria-[current=page]:bg-[image:var(--cortex-sidebar-active)] aria-[current=page]:text-foreground aria-[current=page]:shadow-[inset_0_0_0_1px_var(--cortex-sidebar-active-border)]"
          >
            <span
              aria-hidden="true"
              className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-transparent group-aria-[current=page]:bg-[var(--cortex-sidebar-accent)]"
            />
            <Icon className="size-[1.125rem] shrink-0 text-[var(--cortex-sidebar-icon)] transition-colors duration-150 group-hover:text-foreground group-aria-[current=page]:text-[var(--cortex-sidebar-accent)]" />
            <span className="truncate">{link.label}</span>
            {typeof link.badge === "number" && link.badge > 0 ? (
              <span
                aria-label={`${link.badge} items`}
                className="ml-auto min-w-5 rounded-md border border-[var(--cortex-sidebar-accent)]/35 bg-[var(--cortex-sidebar-accent)]/15 px-1.5 py-0.5 text-center font-mono text-[0.625rem] font-semibold leading-4 text-[var(--cortex-sidebar-accent)]"
              >
                {link.badge > 99 ? "99+" : link.badge}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppSidebar({
  productLabel,
  workspace,
  account,
  activePath,
  primaryLinks,
  secondaryLinks = [],
  utilityLinks = [],
  recentConversations = [],
}: AppSidebarProps) {
  return (
    <aside className="sticky top-0 h-screen border-r border-[var(--cortex-sidebar-border)] bg-[var(--cortex-sidebar-background)] backdrop-blur-xl">
      <div className="flex h-full flex-col px-4 py-5">
        <Link
          href={workspace.href}
          aria-label={`Switch workspace. Current workspace: ${workspace.label}`}
          className="group/context -mx-1 flex min-h-14 items-center gap-3 rounded-lg px-2.5 transition-colors duration-150 hover:bg-[var(--cortex-sidebar-hover)] active:bg-[var(--cortex-sidebar-hover)]"
        >
          <CortexMark className="size-9 shrink-0 transition-transform duration-200 group-hover/context:scale-[1.025]" />
          <span className="min-w-0 flex-1">
            <span className="block font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.12em] text-subtle">
              {productLabel}
            </span>
            <span className="mt-0.5 block truncate text-sm font-medium tracking-[-0.01em] text-foreground">
              {workspace.label}
            </span>
          </span>
          <ChevronLeftIcon className="size-3.5 shrink-0 rotate-180 text-subtle transition-transform duration-150 group-hover/context:translate-x-0.5" />
        </Link>

        <div className="mt-6 flex-1 overflow-y-auto">
          <SidebarNavigation
            label="Workspace navigation"
            links={primaryLinks}
            activePath={activePath}
          />

          <section
            aria-labelledby="recent-conversations-heading"
            className="mt-8 border-t border-[var(--cortex-sidebar-border)] pt-5"
          >
            <h2
              id="recent-conversations-heading"
              className="px-3 font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.13em] text-subtle"
            >
              Recent conversations
            </h2>

            {recentConversations.length > 0 ? (
              <nav aria-label="Recent conversations" className="mt-2 space-y-0.5">
                {recentConversations.slice(0, 5).map((conversation) => {
                  const isActive = activePath === conversation.href;

                  return (
                    <Link
                      key={conversation.id}
                      href={conversation.href}
                      aria-current={isActive ? "page" : undefined}
                      className="block truncate rounded-[var(--cortex-sidebar-item-radius)] px-3 py-2 text-xs leading-5 text-[var(--cortex-sidebar-text)] transition-colors hover:bg-[var(--cortex-sidebar-hover)] hover:text-foreground aria-[current=page]:bg-[var(--cortex-sidebar-hover)] aria-[current=page]:text-foreground"
                    >
                      {conversation.label}
                    </Link>
                  );
                })}
              </nav>
            ) : (
              <p className="px-3 pt-3 text-[0.6875rem] leading-5 text-subtle">
                Your recent questions will appear here.
              </p>
            )}
          </section>
        </div>

        <div className="border-t border-[var(--cortex-sidebar-border)] pt-3">
          {secondaryLinks.length > 0 ? (
            <SidebarNavigation
              label="Workspace settings"
              links={secondaryLinks}
              activePath={activePath}
            />
          ) : null}

          {utilityLinks.length > 0 ? (
            <div className={secondaryLinks.length > 0 ? "mt-1" : undefined}>
              <SidebarNavigation
                label="Application preferences"
                links={utilityLinks}
                activePath={activePath}
              />
            </div>
          ) : null}

          <Link
            href={account.href}
            aria-label={`Account: ${account.label}`}
            className="group/account mt-2 flex min-h-12 items-center gap-3 rounded-[var(--cortex-sidebar-item-radius)] px-2.5 transition-colors duration-150 hover:bg-[var(--cortex-sidebar-hover)] active:bg-[var(--cortex-sidebar-hover)]"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-full border border-[var(--cortex-sidebar-border)] bg-surface/70 font-mono text-xs font-semibold text-foreground">
              {accountInitials(account.label)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">
                {account.label}
              </span>
              <span className="mt-0.5 block truncate text-[0.6875rem] text-subtle">
                {account.detail}
              </span>
            </span>
            <ChevronLeftIcon className="size-3.5 shrink-0 rotate-180 text-subtle opacity-0 transition-[opacity,transform] duration-150 group-hover/account:translate-x-0.5 group-hover/account:opacity-100" />
          </Link>
        </div>
      </div>
    </aside>
  );
}
