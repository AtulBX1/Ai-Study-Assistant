import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import openapiTS, { astToString } from "openapi-typescript";

const frontendDirectory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const repositoryDirectory = path.resolve(frontendDirectory, "..");
const schemaJson = execFileSync(
  "uv",
  [
    "run",
    "--directory",
    path.join(repositoryDirectory, "backend"),
    "python",
    "-c",
    "import json; from app.main import app; print(json.dumps(app.openapi()))",
  ],
  { cwd: repositoryDirectory, encoding: "utf8" },
);

await writeFile(
  path.join(frontendDirectory, "openapi.json"),
  `${JSON.stringify(JSON.parse(schemaJson), null, 2)}\n`,
);
const types = await openapiTS(JSON.parse(schemaJson));
await mkdir(path.join(frontendDirectory, "src", "lib", "api"), {
  recursive: true,
});
await writeFile(
  path.join(frontendDirectory, "src", "lib", "api", "schema.d.ts"),
  astToString(types),
);
