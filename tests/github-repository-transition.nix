# Every repository the site declares, held against the requests that build it
# and against the rendered cluster: the argument for each assertion is in
# github-repository-transition.py's own header, and the roster it loops over is
# `repositories.nix`.
#
# The roster is handed over as JSON rather than read from the file, so the
# derived Secret names the host mints from and the names this gate holds the
# build requests to are one value and cannot drift.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-github-repository-transition" {
  nativeBuildInputs = [ pkgs.gnugrep pkgs.kubectl python ];
  roster = builtins.toJSON (import ../repositories.nix);
  passAsFile = [ "roster" ];
} ''
  set -eu
  root=${../.}

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  python3 ${./github-repository-transition.py} "$rosterPath" rendered.yaml "$root"

  # Reaching a forge at all is the half of the cutover that is not per
  # repository, and these two lines read occurrence counts and nothing else:
  # how many times the public cidr appears in the file, and how many times each
  # of the six exceptions does. Four workloads here mint against GitHub -- the
  # api's arm, the ticket service's, the finalizer's and the importer's -- so
  # every one of those counts is at least four, and a file that lost an
  # exception from one arm falls below it. What any one arm ADMITS is a
  # different question and a grep cannot read it: tests/forge-app-key.py parses
  # each minter's policy out of the render and holds the arm's port, its cidr
  # and its exceptions there.
  #
  # The cidr's own count runs one ahead of the arms: the scheduler writes the
  # same cidr over the cluster's own ranges and mints nothing.
  network="$root/cluster/apps/chuggy-control-plane-network-policy.yaml"
  test "$(grep -c 'cidr: 0.0.0.0/0' "$network")" -ge 4
  for range in 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16; do
    test "$(grep -c -- "- $range" "$network")" -ge 4
  done

  touch "$out"
''
