// Releases the runner package the prepare step packed, on GitHub.
//
// The third step of `publish-runner-release`, and the only one with the token.
// It runs this file and nothing the commit wrote: the commit's code ran in the
// step before and is not read here as anything but a file. It is
// contract-release.mjs for a runner package, and each rule below that one also
// has is argued there.
//
// WHAT THE PREPARE STEP LEFT IS CHECKED, NOT TRUSTED. Every entry is opened
// without following a link and must be a regular file within a size bound, or
// the pack a real directory of at most one tarball, before it is read, and no
// message here carries what a file held. The tag must be `v` and a version;
// the tarball must be named `<package>-<version>.tgz`, which is the address
// kasofsk/chuggy's scripts/pin-runner-release.ts fetches it from; the package
// is the run's parameter and the repository is the package's, so a tarball of
// another package or release is refused. The commit is the run's own
// parameter and not a file.
//
// THE NOTES ARE THE RELEASE COMMIT'S MESSAGE, as runner-prepare.sh reads it,
// and arrive in the file `notes`. They are text of the commit's and are put
// in the release's body as they are, which is what a person publishing by
// hand did with notes they wrote; a line naming the commit and the tarball's
// hash follows them. The title is the tag, as every earlier release's is.
//
// A DRAFT FIRST, SO NO RELEASE IS PUBLISHED WITHOUT ITS ASSET, and a draft a
// failed run left is deleted before a new one is made, as the contract's.
import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, opendirSync, openSync, readFileSync } from "node:fs";
import { join } from "node:path";

const { REPOSITORY, PACKAGE, COMMIT, OUT, TOKEN } = process.env;
// The two addresses are GitHub's. The Task sets neither, and
// tests/runner-release.py sets both to a server of its own.
const API = process.env.GITHUB_API ?? "https://api.github.com";
const UPLOADS = process.env.GITHUB_UPLOADS ?? "https://uploads.github.com";
for (const [name, value] of Object.entries({ REPOSITORY, PACKAGE, COMMIT, OUT, TOKEN })) {
  if (value === undefined || value === "") throw new Error(`${name} is not set`);
}

function say(message) {
  process.stdout.write(`release: ${message}\n`);
}

const NOFOLLOW = constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK;
const TAG_BYTES = 256;
// GitHub refuses a release body past 125,000 characters, and the line this
// adds after the notes is under a thousand bytes.
const NOTES_BYTES = 64 * 1024;
const TARBALL_BYTES = 64 * 1024 * 1024;

// The descriptor of a regular file of at most `limit` bytes, or undefined where
// there is no such entry.
function openFile(path, limit, what) {
  let fd;
  try {
    fd = openSync(path, NOFOLLOW);
  } catch (error) {
    if (error.code === "ENOENT") return undefined;
    throw new Error(`the handoff's ${what} cannot be opened (${error.code})`);
  }
  const stat = fstatSync(fd);
  if (!stat.isFile()) throw new Error(`the handoff's ${what} is not a regular file`);
  if (stat.size > limit) throw new Error(`the handoff's ${what} is larger than ${limit} bytes`);
  return fd;
}

function handoff(name, limit) {
  const fd = openFile(join(OUT, name), limit, name);
  if (fd === undefined) return undefined;
  try {
    return readFileSync(fd, "utf8").trim();
  } finally {
    closeSync(fd);
  }
}

const tag = handoff("tag", TAG_BYTES);
if (tag === undefined) {
  say("the prepare step left no tag: nothing to release");
  process.exit(0);
}
const version = /^v(\d+\.\d+\.\d+)$/u.exec(tag)?.[1];
if (version === undefined) throw new Error("the handoff's tag is not a runner release tag");
if (!/^[a-z0-9][a-z0-9._-]*$/u.test(PACKAGE)) throw new Error(`'${PACKAGE}' is not a package name`);
if (!/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/u.test(REPOSITORY) || REPOSITORY.split("/")[1] !== PACKAGE) {
  throw new Error(`'${REPOSITORY}' is not the repository of ${PACKAGE}`);
}
if (!/^[0-9a-f]{40}$/u.test(COMMIT)) throw new Error(`'${COMMIT}' is not a full commit hash`);
const notes = handoff("notes", NOTES_BYTES);
if (notes === undefined || notes === "") throw new Error("the prepare step left a tag and no notes");

const pack = join(OUT, "pack");
let packed;
{
  let fd;
  try {
    fd = openSync(pack, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  } catch (error) {
    throw new Error(`the handoff's pack cannot be opened as a directory (${error.code})`);
  }
  try {
    const opened = fstatSync(fd);
    const named = lstatSync(pack);
    if (!opened.isDirectory() || named.dev !== opened.dev || named.ino !== opened.ino) {
      throw new Error("the handoff's pack is not the directory that was opened");
    }
    // Two entries are more than a release holds: the listing stops there.
    const directory = opendirSync(pack);
    packed = [];
    try {
      for (let entry = directory.readSync(); entry !== null && packed.length < 2; entry = directory.readSync()) {
        packed.push(entry.name);
      }
    } finally {
      directory.closeSync();
    }
  } finally {
    closeSync(fd);
  }
}
const assetName = `${PACKAGE}-${version}.tgz`;
if (packed.length !== 1 || packed[0] !== assetName) {
  throw new Error(`the pack directory holds ${packed.length === 1 ? "one entry that is not this release's tarball" : "other than one entry"}, and ${assetName} is the release`);
}
const assetFd = openFile(join(pack, assetName), TARBALL_BYTES, "tarball");
if (assetFd === undefined) throw new Error("the handoff's tarball is gone");
let body;
try {
  body = readFileSync(assetFd);
} finally {
  closeSync(assetFd);
}
const sha256 = createHash("sha256").update(body).digest("hex");

const token = readFileSync(TOKEN, "utf8").trim();
if (token === "") throw new Error(`${TOKEN} holds no token`);
const api = `${API}/repos/${REPOSITORY}`;

async function call(url, init, expected) {
  const response = await fetch(url, {
    ...init,
    redirect: "error",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "chuggy-runner-release",
      ...init.headers,
    },
  });
  if (!expected.includes(response.status)) {
    throw new Error(`${init.method} ${url} answered ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  return response.status === 204 ? undefined : response.json();
}

// Every page, to a bound: a release of this tag may be on any of them.
const releases = [];
for (let page = 1; ; page += 1) {
  if (page > 20) throw new Error("more than 2000 releases: the listing is not read to its end");
  const listed = await call(`${api}/releases?per_page=100&page=${page}`, { method: "GET" }, [200]);
  releases.push(...listed);
  if (listed.length < 100) break;
}
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
      body: `${notes}\n\nPacked at ${COMMIT} (sha256 ${sha256}).`,
      draft: true,
    }),
  },
  [201],
);
const uploads = `${UPLOADS}/repos/${REPOSITORY}/releases/${draft.id}/assets`;
if (!draft.upload_url.startsWith(`${uploads}{`)) throw new Error(`the draft's upload address '${draft.upload_url}' is not ${uploads}`);
await call(
  `${uploads}?name=${encodeURIComponent(assetName)}`,
  { method: "POST", headers: { "Content-Type": "application/x-gtar" }, body },
  [201],
);
await call(
  `${api}/releases/${draft.id}`,
  { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft: false }) },
  [200],
);
say(`released ${tag} of ${PACKAGE} at ${COMMIT} (sha256 ${sha256})`);
