const LAST_WORKSPACE_KEY_PREFIX = "cortex:last-workspace:";

function storageKey(userId: string) {
  return `${LAST_WORKSPACE_KEY_PREFIX}${userId}`;
}

export function getLastWorkspaceId(userId: string) {
  try {
    return window.localStorage.getItem(storageKey(userId));
  } catch {
    return null;
  }
}

export function rememberLastWorkspace(userId: string, workspaceId: string) {
  try {
    window.localStorage.setItem(storageKey(userId), workspaceId);
  } catch {
    // Resuming a workspace is an enhancement; navigation still works without storage.
  }
}

export function forgetLastWorkspace(userId: string) {
  try {
    window.localStorage.removeItem(storageKey(userId));
  } catch {
    // Ignore unavailable browser storage.
  }
}
