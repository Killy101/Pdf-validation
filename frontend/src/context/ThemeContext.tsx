"use client";

import React, { createContext, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark";
export type ThemeMode = "system" | "light" | "dark";

interface ThemeContextType {
  theme: Theme;
  themeMode: ThemeMode;
  setTheme: (theme: Theme) => void;
  setThemeMode: (mode: ThemeMode) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = "reflink_theme";

// Calculate active theme from time: 6:00 PM (18) to 6:00 AM (6) is dark mode.
export function getAutoTimeTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const hour = new Date().getHours();
  return hour >= 18 || hour < 6 ? "dark" : "light";
}

// Theme provider supporting system time-based auto, light, and dark modes.
export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [themeMode, setThemeModeState] = useState<ThemeMode>("system");
  const [theme, setThemeState] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
      if (saved === "system" || saved === "light" || saved === "dark") {
        setThemeModeState(saved);
        setThemeState(saved === "system" ? getAutoTimeTheme() : saved);
      } else {
        setThemeModeState("system");
        setThemeState(getAutoTimeTheme());
      }
    } catch {
      // Storage access may be restricted in sandboxes.
      setThemeState(getAutoTimeTheme());
    }
    setMounted(true);
  }, []);

  // Update theme when themeMode changes or when system mode time window transitions.
  useEffect(() => {
    if (!mounted) return;

    const resolveTheme = (): Theme => {
      if (themeMode === "system") {
        return getAutoTimeTheme();
      }
      return themeMode;
    };

    setThemeState(resolveTheme());

    if (themeMode === "system") {
      const interval = setInterval(() => {
        setThemeState(resolveTheme());
      }, 30000);
      return () => clearInterval(interval);
    }
  }, [themeMode, mounted]);

  useEffect(() => {
    if (!mounted) return;
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
      root.classList.remove("light");
      root.setAttribute("data-theme", "dark");
      root.style.colorScheme = "dark";
    } else {
      root.classList.remove("dark");
      root.classList.add("light");
      root.setAttribute("data-theme", "light");
      root.style.colorScheme = "light";
    }

    try {
      localStorage.setItem(STORAGE_KEY, themeMode);
    } catch {
      // Storage write error ignored.
    }
  }, [theme, themeMode, mounted]);

  const setThemeMode = (newMode: ThemeMode) => {
    setThemeModeState(newMode);
    if (newMode === "system") {
      setThemeState(getAutoTimeTheme());
    } else {
      setThemeState(newMode);
    }
  };

  const setTheme = (newTheme: Theme) => {
    setThemeMode(newTheme);
  };

  const toggleTheme = () => {
    setThemeMode(theme === "dark" ? "light" : "dark");
  };

  return (
    <ThemeContext.Provider value={{ theme, themeMode, setTheme, setThemeMode, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = (): ThemeContextType => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
};
