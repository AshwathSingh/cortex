"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AccountSettings } from "@/components/account/account-settings";
import { ApiError, apiRequest } from "@/lib/api";
import type { AuthenticatedUser } from "@/lib/api-types";
import { routes } from "@/lib/routes";

export function StandaloneAccountSettings() {
  const router = useRouter();
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadUser() {
      try {
        setUser(
          await apiRequest<AuthenticatedUser>("/api/auth/me", {
            signal: controller.signal,
          }),
        );
      } catch (requestError) {
        if (controller.signal.aborted) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          router.replace("/login");
          return;
        }
        setError(
          requestError instanceof ApiError
            ? requestError.message
            : "Unable to load your account.",
        );
      }
    }

    void loadUser();
    return () => controller.abort();
  }, [router]);

  return (
    <AccountSettings
      user={user}
      loadError={error}
      backHref={routes.workspaces}
      backLabel="All workspaces"
    />
  );
}
