import { useEffect, useState } from "react";

export type Appearance = "system" | "light" | "dark";
export const APPEARANCE_KEY = "ai-lab.appearance";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function isAppearance(value: unknown): value is Appearance {
  return value === "system" || value === "light" || value === "dark";
}

export function readAppearance(): Appearance {
  try {
    const saved = localStorage.getItem(APPEARANCE_KEY);
    return isAppearance(saved) ? saved : "system";
  } catch {
    return "system";
  }
}

export function applyAppearance(preference: Appearance) {
  const theme =
    preference === "system"
      ? window.matchMedia(DARK_QUERY).matches
        ? "dark"
        : "light"
      : preference;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

export function useAppearance() {
  const [appearance, setAppearance] = useState<Appearance>(readAppearance);
  useEffect(() => {
    applyAppearance(appearance);
    const media = window.matchMedia(DARK_QUERY);
    const update = () => {
      if (appearance === "system") applyAppearance("system");
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [appearance]);

  function changeAppearance(value: Appearance) {
    setAppearance(value);
    applyAppearance(value);
    try {
      localStorage.setItem(APPEARANCE_KEY, value);
    } catch {
      /* Restricted storage: appearance still works for this session. */
    }
  }
  return { appearance, changeAppearance };
}
