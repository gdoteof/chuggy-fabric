// Releases the worker contract the prepare step packed, on GitHub.
//
// The third step of `publish-worker-contract`, and the only one with the
// token. It runs this file and nothing the commit wrote: the commit's code ran
// in the step before and is not read here as anything but a file.
//
// WHAT THE PREPARE STEP LEFT IS CHECKED, NOT TRUSTED. The tag must be the one
// pattern a worker contract is released under, the commit is the run's own
// parameter and not a file, and the tarball is the one regular file the pack
// directory holds. The title and the notes are written here.
//
// A DRAFT FIRST, SO NO RELEASE IS PUBLISHED WITHOUT ITS ASSET. A consumer
// installs the asset by its URL, and a published release with no asset is a
// URL that does not resolve. The release is made a draft, the asset is
// uploaded, and then it is published, which makes the tag at the commit. A
// draft a failed run left is deleted before a new one is made: it holds no
// tag, so nothing else would find it, and the retry would make a second.
//
// NOT `gh`: its release command would be the same three calls, and this
// step's image would then be one more that has to carry it.
import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const { REPOSITORY, COMMIT, OUT, TOKEN } = process.env;
// The two addresses are GitHub's. The Task sets neither, and
// tests/contract-release.py sets both to a server of its own.
const API = process.env.GITHUB_API ?? "https://api.github.com";
const UPLOADS = process.env.GITHUB_UPLOADS ?? "https://uploads.github.com";
for (const [name, value] of Object.entries({ REPOSITORY, COMMIT, OUT, TOKEN })) {
  if (value === undefined || value === "") throw new Error(`${name} is not set`);
}

function say(message) {
  process.stdout.write(`release: ${message}\n`);
}

let tag;
try {
  tag = readFileSync(join(OUT, "tag"), "utf8").trim();
} catch (error) {
  if (error.code !== "ENOENT") throw error;
  say("the prepare step left no tag: nothing to release");
  process.exit(0);
}
if (!/^worker-contract-v\d+\.\d+\.\d+$/u.test(tag)) throw new Error(`'${tag}' is not a worker contract tag`);
if (!/^[0-9a-f]{40}$/u.test(COMMIT)) throw new Error(`'${COMMIT}' is not a full commit hash`);
if (!/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/u.test(REPOSITORY)) throw new Error(`'${REPOSITORY}' is not a repository`);

const packed = readdirSync(join(OUT, "pack"));
if (packed.length !== 1 || !/^[A-Za-z0-9._-]+\.tgz$/u.test(packed[0])) {
  throw new Error(`the pack directory holds ${JSON.stringify(packed)}, and one tarball is the release`);
}
const asset = join(OUT, "pack", packed[0]);
if (!lstatSync(asset).isFile()) throw new Error(`${asset} is not a regular file`);
const body = readFileSync(asset);
const sha256 = createHash("sha256").update(body).digest("hex");

const token = readFileSync(TOKEN, "utf8").trim();
if (token === "") throw new Error(`${TOKEN} holds no token`);
const api = `${API}/repos/${REPOSITORY}`;

async function call(url, init, expected) {
  const response = await fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "chuggy-contract-publish",
      ...init.headers,
    },
  });
  if (!expected.includes(response.status)) {
    throw new Error(`${init.method} ${url} answered ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  return response.status === 204 ? undefined : response.json();
}

const releases = await call(`${api}/releases?per_page=100`, { method: "GET" }, [200]);
if (releases.some((release) => release.tag_name === tag && !release.draft)) {
  say(`${tag} is already released: nothing to release`);
  process.exit(0);
}
for (const stale of releases.filter((release) => release.tag_name === tag && release.draft)) {
  await call(`${api}/releases/${stale.id}`, { method: "DELETE" }, [204]);
  say(`deleted the draft ${stale.id} an earlier run left`);
}

const draft = await call(
  `${api}/releases`,
  {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tag_name: tag,
      target_commitish: COMMIT,
      name: tag,
      body: `Packed at ${COMMIT} (sha256 ${sha256}).`,
      draft: true,
    }),
  },
  [201],
);
const uploads = `${UPLOADS}/repos/${REPOSITORY}/releases/${draft.id}/assets`;
if (!draft.upload_url.startsWith(`${uploads}{`)) throw new Error(`the draft's upload address '${draft.upload_url}' is not ${uploads}`);
await call(
  `${uploads}?name=${encodeURIComponent(packed[0])}`,
  { method: "POST", headers: { "Content-Type": "application/gzip" }, body },
  [201],
);
await call(
  `${api}/releases/${draft.id}`,
  { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft: false }) },
  [200],
);
say(`released ${tag} at ${COMMIT} (sha256 ${sha256})`);
