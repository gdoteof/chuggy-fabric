#!/usr/bin/env bash
# The release manifests `scripts/check-release-consistency` names identify one
# source.
#
# That script states and enforces the rule; this runs it over `cluster/apps`,
# where it reads the manifests its own `API_MANIFESTS` and `WEB_MANIFESTS` name
# and no other file in the directory. It holds that those control-plane
# manifests select one API image digest, that the two consoles select different
# web digests, that all of them annotate the same source commit, and that the
# migrate Job is named for that commit. `tests/release-images.nix` drives that
# script through every refusal it states; `tests/chug-ci.nix` drives this file
# against a refused tree and against trees it cannot run in, so what proves
# either bites is not this file.
#
# THIS IS THE PORTABLE SUBSET, NOT THE FABRIC'S GATE. `nix flake check` builds
# the hosts, holds the assertions and warnings a host is refused or warned by,
# and runs the rendered-manifest gates. None of it runs here: the image an
# evaluation runs in carries python3 and git, and neither Nix nor kubectl. Its
# checks read the tree, this file included, so what a change still needs run is
# read off `flake.nix` rather than assumed from this gate passing.
#
# Exit 0 clean, 1 on a finding, 2 when it could not run. Exit 2 is not a pass.
set -o errexit -o nounset -o pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
check=$root/scripts/check-release-consistency
manifests=$root/cluster/apps

command -v python3 >/dev/null 2>&1 ||
  { echo "cannot run: python3 is not on PATH" >&2; exit 2; }
[ -f "$check" ] || { echo "cannot run: $check is missing" >&2; exit 2; }
[ -d "$manifests" ] ||
  { echo "cannot run: $manifests is not a directory" >&2; exit 2; }

# `refuse()` in that script exits 3 and nothing else does; a SyntaxError in it
# exits 1 like a refusal would have, and reporting that as a finding sends a
# reader to the manifests.
status=0
python3 "$check" "$manifests" || status=$?
case $status in
  0) ;;
  3) exit 1 ;;
  *) echo "cannot run: $check exited $status" >&2; exit 2 ;;
esac

echo "clean: the manifests scripts/check-release-consistency names in cluster/apps identify one source; nix flake check did not run"
