import { useEffect, useSyncExternalStore } from "react";

// One theme for the whole page. Every component calling useTheme() reads the
// same value, so toggling it in the header also updates App's loading screen,
// the About page and the login screen.
let theme = null;
const listeners = new Set();

function getTheme() {
  theme ??= localStorage.getItem("theme") || "dark";
  return theme;
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function useTheme() {
  const current = useSyncExternalStore(subscribe, getTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-bs-theme", current);
    localStorage.setItem("theme", current);
  }, [current]);

  const toggleTheme = () => {
    theme = getTheme() === "dark" ? "light" : "dark";
    listeners.forEach((listener) => listener());
  };

  return {
    theme: current,
    toggleTheme,
  };
}

export default useTheme;
