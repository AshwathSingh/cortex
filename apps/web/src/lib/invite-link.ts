import { routes } from "@/lib/routes";

export const INVITE_ACCEPT_PATH = "/invites/accept";
const PENDING_INVITE_TOKEN_KEY = "cortex:pending-invite-token";

export function createInviteLink(origin: string, token: string) {
  const params = new URLSearchParams({ token });
  return `${origin}${INVITE_ACCEPT_PATH}#${params.toString()}`;
}

function storedToken() {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(PENDING_INVITE_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function capturePendingInviteToken() {
  if (typeof window === "undefined") return null;

  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const token = fragment.get("token")?.trim() || null;
  if (!token) return storedToken();

  try {
    window.sessionStorage.setItem(PENDING_INVITE_TOKEN_KEY, token);
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
  } catch {
    // Keep the fragment intact if storage is unavailable so the token is not lost.
  }
  return token;
}

export function clearPendingInviteToken() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(PENDING_INVITE_TOKEN_KEY);
  } catch {
    // A completed invite does not need to fail because storage is unavailable.
  }
}

export function postAuthDestination() {
  return storedToken() ? INVITE_ACCEPT_PATH : routes.workspaces;
}
