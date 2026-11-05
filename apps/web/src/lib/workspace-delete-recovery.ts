export type PendingWorkspaceDeletion = {
  workspaceId: string;
  workspaceName: string;
};

const PENDING_DELETIONS_KEY_PREFIX = "cortex:pending-workspace-deletions:";

function storageKey(userId: string) {
  return `${PENDING_DELETIONS_KEY_PREFIX}${userId}`;
}

function isPendingDeletion(value: unknown): value is PendingWorkspaceDeletion {
  return (
    typeof value === "object" &&
    value !== null &&
    "workspaceId" in value &&
    typeof value.workspaceId === "string" &&
    "workspaceName" in value &&
    typeof value.workspaceName === "string"
  );
}

export function getPendingWorkspaceDeletions(
  userId: string,
): PendingWorkspaceDeletion[] {
  try {
    const stored = window.localStorage.getItem(storageKey(userId));
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed.filter(isPendingDeletion) : [];
  } catch {
    return [];
  }
}

export function rememberPendingWorkspaceDeletion(
  userId: string,
  deletion: PendingWorkspaceDeletion,
) {
  try {
    const current = getPendingWorkspaceDeletions(userId).filter(
      (candidate) => candidate.workspaceId !== deletion.workspaceId,
    );
    window.localStorage.setItem(
      storageKey(userId),
      JSON.stringify([...current, deletion]),
    );
    return true;
  } catch {
    // Recovery remains available in the open confirmation modal.
    return false;
  }
}

export function forgetPendingWorkspaceDeletion(
  userId: string,
  workspaceId: string,
) {
  try {
    const remaining = getPendingWorkspaceDeletions(userId).filter(
      (candidate) => candidate.workspaceId !== workspaceId,
    );
    if (remaining.length === 0) {
      window.localStorage.removeItem(storageKey(userId));
      return;
    }
    window.localStorage.setItem(storageKey(userId), JSON.stringify(remaining));
  } catch {
    // A stale recovery record is harmless; the API still authorizes every retry.
  }
}
