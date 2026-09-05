import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { APPEARANCE_KEY, readAppearance, useAppearance } from "./appearance";

afterEach(() => vi.unstubAllGlobals());
it("follows system changes, persists explicit choices, and restores them on reload", () => {
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  });
  let dark = false;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", () => ({
    matches: dark,
    addEventListener: (_: string, listener: () => void) =>
      listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) =>
      listeners.delete(listener),
  }));
  const hook = renderHook(useAppearance);
  expect(document.documentElement.dataset.theme).toBe("light");
  act(() => {
    dark = true;
    listeners.forEach((listener) => listener());
  });
  expect(document.documentElement.dataset.theme).toBe("dark");
  act(() => hook.result.current.changeAppearance("light"));
  expect(storage.get(APPEARANCE_KEY)).toBe("light");
  act(() => listeners.forEach((listener) => listener()));
  expect(document.documentElement.dataset.theme).toBe("light");
  hook.unmount();
  const reloaded = renderHook(useAppearance);
  expect(reloaded.result.current.appearance).toBe("light");
  act(() => reloaded.result.current.changeAppearance("system"));
  expect(document.documentElement.dataset.theme).toBe("dark");
  reloaded.unmount();
  expect(listeners.size).toBe(0);
  storage.set(APPEARANCE_KEY, "invalid");
  expect(readAppearance()).toBe("system");
});
