const { execSync } = require("child_process");

const vars = JSON.parse(
  execSync("railway variables --service war-machine --json", { encoding: "utf8" }),
);
const token = vars.INTERNAL_SCAN_TOKEN;
const body = JSON.stringify({ hours: 24, source: "producthunt_ai" });

const out = execSync(
  `curl.exe -s -w "\\nHTTP:%{http_code}" -X POST "https://war-machine-production.up.railway.app/scrape" -H "Content-Type: application/json" -H "x-internal-scan-token: ${token}" -d "${body.replace(/"/g, '\\"')}"`,
  { encoding: "utf8" },
);
console.log(out);
