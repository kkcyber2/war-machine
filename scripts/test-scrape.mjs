const { execSync } = require("child_process");

const vars = JSON.parse(
  execSync("railway variables --service war-machine --json", { encoding: "utf8" }),
);
const token = vars.INTERNAL_SCAN_TOKEN;
if (!token) {
  console.error("INTERNAL_SCAN_TOKEN missing");
  process.exit(1);
}

const body = JSON.stringify({ hours: 24, source: "producthunt_ai" });
const cmd = [
  "curl.exe",
  "-s",
  "-w",
  "\\nHTTP:%{http_code}",
  "-X",
  "POST",
  "https://war-machine-production.up.railway.app/scrape",
  "-H",
  "Content-Type: application/json",
  "-H",
  `x-internal-scan-token: ${token}`,
  "-d",
  body,
].join(" ");

console.log(execSync(cmd, { encoding: "utf8" }));
