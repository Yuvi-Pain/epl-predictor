// Generate src/api/schema.gen.ts from the backend's OpenAPI schema.
//
//   npm run gen:api                  # from the running backend
//   npm run gen:api -- openapi.json  # from a saved schema file
//   npm run check:api                # exit 1 if the committed types are stale
//
// The backend URL defaults to http://localhost:8000; set BACKEND_URL to change
// it (inside Docker Compose it is already set to http://backend:8000).
import { readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const OUT = new URL("../src/api/schema.gen.ts", import.meta.url);
const HEADER =
  "// Generated from the backend's OpenAPI schema by scripts/gen-api-types.mjs.\n" +
  "// Do not edit by hand: run `npm run gen:api` after changing the API.\n\n";

const args = process.argv.slice(2);
const check = args.includes("--check");
const source = args.find((a) => !a.startsWith("--"));
const schemaUrl = source
  ? pathToFileURL(source)
  : new URL("/openapi.json", process.env.BACKEND_URL ?? "http://localhost:8000");

let ast;
try {
  ast = await openapiTS(schemaUrl);
} catch (err) {
  console.error(`Could not read the OpenAPI schema from ${schemaUrl}. Is the backend running?`);
  console.error(err instanceof Error ? err.message : err);
  process.exit(2);
}
const generated = HEADER + astToString(ast);

if (check) {
  // Compare ignoring CRLF: Windows checkouts (core.autocrlf) convert the file.
  const current = (await readFile(OUT, "utf8").catch(() => "")).replace(/\r\n/g, "\n");
  if (current !== generated) {
    console.error("src/api/schema.gen.ts is out of date with the backend. Run `npm run gen:api`.");
    process.exit(1);
  }
  console.log("API types are up to date.");
} else {
  await writeFile(OUT, generated);
  console.log(`Wrote src/api/schema.gen.ts from ${schemaUrl}`);
}
