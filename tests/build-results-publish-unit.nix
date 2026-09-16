{ pkgs, host }:

# The publisher unit a host builds can answer a build request with the
# consumer it names.
#
# `modules/build-provenance.nix` hands the unit `SCRIPTS_PATH`, a store copy of
# `scripts/`, and a script whose PATH carries the python3 the consumer runs
# under; `scripts/publish-build-results` then runs `fulfil-build-requests` from
# the first with the second. Nothing about that is typed: an evaluation is
# equally happy with a `SCRIPTS_PATH` naming a directory that lacks the
# consumer, a copy of `scripts/` whose siblings do not resolve from a read-only
# store path, and a PATH with no python3 on it -- and `tests/build-results-
# publish.nix` drives the publisher over a copy of `scripts/` with the build's
# own tools on PATH, which is a different arrangement from the one this host
# runs. So this reads the built unit -- its environment off the host's closure
# and its PATH off the built script -- and drives the consumer from exactly
# there over one request, with that PATH and no other.
#
# A runCommand and not a VM, because the question is what the unit was built
# with and booting a machine to answer it would cost minutes and answer no
# more. What it therefore does not say is that the timer fires or the push
# lands; the publisher's own suite holds the push, and the box is the only
# thing that has seen the timer.

let
  unit = host.config.systemd.services.chuggy-build-results-publish;
  # A store path with its context, so the copy of `scripts/` the unit names is
  # an input of this derivation rather than a path that happens to exist.
  scriptsPath = unit.environment.SCRIPTS_PATH;
  # "/nix/store/...-chuggy-build-results-publish/bin/chuggy-build-results-publish".
  execStart = unit.serviceConfig.ExecStart;
  # Any full commit: what is driven is the arrangement, not a build.
  commit = "0123456789abcdef0123456789abcdef01234567";
in
pkgs.runCommand "chuggy-build-results-publish-unit-${host.config.networking.hostName}" {
  nativeBuildInputs = [ pkgs.coreutils pkgs.gnugrep ];
} ''
  set -eu
  scripts='${scriptsPath}'
  script='${execStart}'

  for name in fulfil-build-requests build_sources.py render-build-request request-build; do
    [ -f "$scripts/$name" ] ||
      { echo "SCRIPTS_PATH $scripts carries no $name" >&2; exit 1; }
  done

  # The PATH the consumer runs under is the one the built script exports, not
  # the unit's own: the module puts python3 in the script's runtime inputs and
  # nowhere else, so that line is what says whether python3 is there.
  exported=$(grep -m1 '^export PATH=' "$script") ||
    { echo "$script exports no PATH, so what the consumer runs under is unknown" >&2; exit 1; }
  eval "$exported"
  command -v python3 >/dev/null ||
    { echo "the unit's PATH carries no python3: $PATH" >&2; exit 1; }

  # One request filed and answered from the store copy, which is the whole of
  # what the publisher asks of it: the document written by the site's own
  # writer, the builds rendered through the sibling the consumer resolves
  # beside itself.
  mkdir work
  python3 "$scripts/request-build" --repository-id chuggy --source-commit ${commit} --root work \
    >filed || { echo "request-build could not file from $scripts" >&2; exit 1; }
  python3 "$scripts/fulfil-build-requests" --root work >rendered ||
    { echo "fulfil-build-requests could not answer from $scripts" >&2; exit 1; }
  [ -s rendered ] ||
    { echo "the consumer rendered nothing for the request it was given" >&2; cat filed >&2; exit 1; }
  while read -r rendered_path; do
    [ -f "work/$rendered_path" ] ||
      { echo "the consumer reported $rendered_path and did not write it" >&2; exit 1; }
    case $rendered_path in
      builds/chuggy/${commit}/*.yaml) ;;
      *) echo "the consumer wrote $rendered_path, which is not a build of the request" >&2; exit 1 ;;
    esac
  done <rendered
  touch "$out"
''
