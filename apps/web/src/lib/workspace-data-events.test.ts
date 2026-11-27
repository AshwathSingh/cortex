import { expect, it, vi } from "vitest";
import { notifySourceRemoval, subscribeSourceRemovals } from "./workspace-data-events";

it("refreshes only the affected workspace and unsubscribes cleanly", () => {
  const affected = vi.fn(), other = vi.fn();
  const off = subscribeSourceRemovals("a", affected);
  const offOther = subscribeSourceRemovals("b", other);
  notifySourceRemoval("a");
  expect(affected).toHaveBeenCalledOnce();
  expect(other).not.toHaveBeenCalled();
  off(); offOther(); notifySourceRemoval("a");
  expect(affected).toHaveBeenCalledOnce();
});

it("refreshes another tab from a source removal notification", () => {
  const refresh = vi.fn();
  const off = subscribeSourceRemovals("a", refresh);
  window.dispatchEvent(new StorageEvent("storage", {key:"cortex:source-removal",newValue:JSON.stringify({workspaceId:"a",revision:"new"})}));
  expect(refresh).toHaveBeenCalledOnce();
  off();
});
