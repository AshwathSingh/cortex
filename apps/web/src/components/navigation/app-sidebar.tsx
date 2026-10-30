import type { ComponentType } from "react";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { CortexMark } from "@/components/brand/cortex-mark";

import {
  ChevronLeftIcon,
  ComposeIcon,
} from "./sidebar-icons";

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
  isActive: boolean;
  onSelect: () => void;
};

type AppSidebarProps = {
  productLabel: string;
  workspace: {
    id: string;
    label: string;
    options: {
      id: string;
      label: string;
      detail: string;
      href: string;
    }[];
    createHref: string;
  };
  account: { label: string; detail: string; href: string };
  activePath: string;
  primaryLinks: SidebarLink[];
  secondaryLinks?: SidebarLink[];
  utilityLinks?: SidebarLink[];
  recentConversations?: SidebarConversation[];
  onNewConversation?: () => void;
};

function WorkspaceSwitcher({
  productLabel,
  workspace,
}: Pick<AppSidebarProps, "productLabel" | "workspace">) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    function closeOnOutsidePress(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    }

    document.addEventListener("pointerdown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isOpen]);

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={isOpen}
        aria-controls="workspace-switcher-menu"
        aria-label={`Switch workspace. Current workspace: ${workspace.label}`}
        onClick={() => setIsOpen((open) => !open)}
        className="group/context flex min-h-13 w-full items-center gap-2.5 rounded-[var(--cortex-sidebar-item-radius)] px-2 text-left transition-colors duration-150 hover:bg-[var(--cortex-sidebar-hover)] active:bg-[var(--cortex-sidebar-hover)]"
      >
        <CortexMark className="size-8 shrink-0 transition-transform duration-200 group-hover/context:scale-[1.025]" />
        <span className="min-w-0 flex-1">
          <span className="block text-[0.625rem] font-semibold uppercase tracking-[0.11em] text-subtle">
            {productLabel}
          </span>
          <span className="mt-0.5 block truncate text-[0.8125rem] font-semibold tracking-[-0.01em] text-foreground">
            {workspace.label}
          </span>
        </span>
        <ChevronLeftIcon
          className={`size-3.5 shrink-0 text-subtle transition-transform duration-150 ${
            isOpen
              ? "rotate-90"
              : "rotate-180 group-hover/context:translate-x-0.5"
          }`}
        />
      </button>

      {isOpen ? (
        <nav
          id="workspace-switcher-menu"
          aria-label="Workspaces"
          className="absolute left-[calc(100%+0.75rem)] top-0 z-50 w-72 overflow-hidden rounded-xl border border-border/40 bg-surface-raised shadow-[0_22px_70px_rgb(0_0_0/42%)]"
        >
          <div className="border-b border-border/25 px-4 py-3">
            <p className="text-[0.8125rem] font-semibold text-foreground">Switch workspace</p>
            <p className="mt-0.5 text-xs text-subtle">
              Choose a project context.
            </p>
          </div>
          <div className="max-h-72 overflow-y-auto p-2">
            {workspace.options.length > 0 ? (
              workspace.options.map((option) => {
                const isCurrent = option.id === workspace.id;
                return (
                  <Link
                    key={option.id}
                    href={option.href}
                    aria-current={isCurrent ? "page" : undefined}
                    onClick={() => setIsOpen(false)}
                    className="flex min-h-12 items-center gap-3 rounded-lg px-3 transition-colors hover:bg-surface aria-[current=page]:bg-accent/10"
                  >
                    <span
                      aria-hidden="true"
                      className={`size-2 rounded-full ${
                        isCurrent ? "bg-accent-bright" : "bg-border-strong"
                      }`}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[0.8125rem] font-medium text-foreground">
                        {option.label}
                      </span>
                      <span className="mt-0.5 block text-xs capitalize text-subtle">
                        {option.detail.toLowerCase()}
                      </span>
                    </span>
                    {isCurrent ? (
                      <span className="text-[0.6875rem] font-semibold text-accent-bright">
                        Current
                      </span>
                    ) : null}
                  </Link>
                );
              })
            ) : (
              <p className="px-3 py-4 text-xs text-subtle">Loading workspaces…</p>
            )}
          </div>
          <div className="border-t border-border/25 p-2">
            <Link
              href={workspace.createHref}
              onClick={() => setIsOpen(false)}
              className="flex min-h-10 items-center gap-2 rounded-lg px-3 text-sm font-medium text-muted transition-colors hover:bg-surface hover:text-foreground"
            >
              <span aria-hidden="true" className="text-lg leading-none">+</span>
              New workspace
            </Link>
          </div>
        </nav>
      ) : null}
    </div>
  );
}

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
            className="group relative flex min-h-10 items-center gap-2.5 rounded-[var(--cortex-sidebar-item-radius)] px-2.5 text-[0.8125rem] font-medium text-[var(--cortex-sidebar-text)] transition-[background,color] duration-150 ease-out hover:bg-[var(--cortex-sidebar-hover)] hover:text-foreground active:bg-[var(--cortex-sidebar-hover)] aria-[current=page]:bg-[image:var(--cortex-sidebar-active)] aria-[current=page]:text-foreground"
          >
            <span
              aria-hidden="true"
              className="absolute inset-y-2.5 left-0 w-0.5 rounded-full bg-transparent group-aria-[current=page]:bg-[var(--cortex-sidebar-accent)]"
            />
            <Icon className="size-4 shrink-0 text-[var(--cortex-sidebar-icon)] transition-colors duration-150 group-hover:text-foreground group-aria-[current=page]:text-[var(--cortex-sidebar-accent)]" />
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
  onNewConversation,
}: AppSidebarProps) {
  return (
    <aside className="sticky top-0 z-20 h-screen border-r border-[var(--cortex-sidebar-border)] bg-[var(--cortex-sidebar-background)] backdrop-blur-md">
      <div className="flex h-full flex-col px-3.5 py-4">
        <WorkspaceSwitcher productLabel={productLabel} workspace={workspace} />

        <div className="mt-4 flex-1 overflow-y-auto">
          <SidebarNavigation
            label="Workspace navigation"
            links={primaryLinks}
            activePath={activePath}
          />

          {onNewConversation ? (
            <button
              type="button"
              onClick={onNewConversation}
              aria-label="Start new conversation"
              className="group/new-conversation mt-3 flex min-h-9 w-full items-center gap-2.5 rounded-[var(--cortex-sidebar-item-radius)] px-2.5 text-left text-[0.8125rem] font-medium text-[var(--cortex-sidebar-text)] transition-colors hover:bg-[var(--cortex-sidebar-hover)] hover:text-foreground"
            >
              <ComposeIcon className="size-4 shrink-0 text-[var(--cortex-sidebar-icon)] transition-colors group-hover/new-conversation:text-[var(--cortex-sidebar-accent)]" />
              <span>New conversation</span>
            </button>
          ) : null}

          <section
            aria-labelledby="recent-conversations-heading"
            className="mt-4 border-t border-[var(--cortex-sidebar-border)] pt-4"
          >
            <h2
              id="recent-conversations-heading"
              className="px-2.5 text-[0.6875rem] font-semibold tracking-[0.035em] text-subtle"
            >
              Recents
            </h2>

            {recentConversations.length > 0 ? (
              <nav aria-label="Recent conversations" className="mt-2 space-y-0.5">
                {recentConversations.slice(0, 5).map((conversation) => {
                  return (
                    <button
                      key={conversation.id}
                      type="button"
                      onClick={conversation.onSelect}
                      aria-current={conversation.isActive ? "page" : undefined}
                      className="min-h-8 w-full truncate rounded-[var(--cortex-sidebar-item-radius)] px-2.5 py-1.5 text-left text-[0.8125rem] leading-5 text-[var(--cortex-sidebar-text)] transition-colors hover:bg-[var(--cortex-sidebar-hover)] hover:text-foreground aria-[current=page]:bg-[var(--cortex-sidebar-hover)] aria-[current=page]:font-medium aria-[current=page]:text-foreground"
                    >
                      {conversation.label}
                    </button>
                  );
                })}
              </nav>
            ) : (
              <p className="px-2.5 pt-2 text-xs leading-[1.45] text-subtle">
                Your conversations will appear here for this session.
              </p>
            )}
          </section>
        </div>

        <div className="border-t border-[var(--cortex-sidebar-border)] pt-2.5">
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
            className="group/account mt-1 flex min-h-12 items-center gap-2.5 rounded-[var(--cortex-sidebar-item-radius)] px-2 transition-colors duration-150 hover:bg-[var(--cortex-sidebar-hover)] active:bg-[var(--cortex-sidebar-hover)]"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-full border border-[var(--cortex-sidebar-border)] bg-surface/70 font-mono text-xs font-semibold text-foreground">
              {accountInitials(account.label)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[0.8125rem] font-semibold text-foreground">
                {account.label}
              </span>
              <span className="mt-0.5 block truncate text-xs text-subtle">
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
