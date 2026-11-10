// electron-builder custom signing hook: every file it signs (app exe, installer, uninstaller) goes through sign.ps1,
// so the desktop app and the validation engine use the same certificate settings.
const { execFileSync } = require("node:child_process");
const path = require("node:path");

exports.default = async function sign(configuration) {
  execFileSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    path.join(__dirname, "sign.ps1"), "-Path", configuration.path], { stdio: "inherit" });
};
