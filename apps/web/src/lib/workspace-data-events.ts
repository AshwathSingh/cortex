const EVENT = "cortex:source-removed";
const STORAGE_KEY = "cortex:source-removal";

/** Refresh mounted workspace views, including another tab on the same origin. */
export function notifySourceRemoval(workspaceId: string) {
  window.dispatchEvent(new CustomEvent(EVENT, { detail: workspaceId }));
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ workspaceId, revision: crypto.randomUUID() }),
    );
  } catch {
    /* Local events still work when storage is unavailable. */
  }
}

export function subscribeSourceRemovals(
  workspaceId: string,
  refresh: () => void,
) {
  function local(event: Event) {
    if ((event as CustomEvent<string>).detail === workspaceId) refresh();
  }
  function remote(event: StorageEvent) {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try {
      if (JSON.parse(event.newValue).workspaceId === workspaceId) refresh();
    } catch {
      /* Ignore invalid storage. */
    }
  }
  window.addEventListener(EVENT, local);
  window.addEventListener("storage", remote);
  return () => {
    window.removeEventListener(EVENT, local);
    window.removeEventListener("storage", remote);
  };
}
