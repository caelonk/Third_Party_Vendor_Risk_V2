// Set the theme before first paint so there is no flash of the wrong theme.
// A static file (not an inline <script>) so the CSP can be script-src 'self'.
(function () {
  try {
    var stored = localStorage.getItem("vr-theme"); // "light" | "dark" | "system"
    var system = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var resolved = !stored || stored === "system" ? system : stored;
    document.documentElement.setAttribute("data-theme", resolved);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "light");
  }
})();
