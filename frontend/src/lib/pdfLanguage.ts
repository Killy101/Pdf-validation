const scripts: Record<string, string> = {"und-Arab": "Arabic script; language not determined", "und-Hebr": "Hebrew script; language not determined",
  "und-Hani": "Han script; language not determined", "und-Grek": "Greek script; language not determined", "und-Thai": "Thai script; language not determined"};

export function pdfLanguageName(code: string): string {
  if (!code || code === "unknown") return "Language not determined";
  if (scripts[code]) return scripts[code];
  try {
    return new Intl.DisplayNames(["en"], {type: "language"}).of(code) || code;
  } catch {
    return code;
  }
}
