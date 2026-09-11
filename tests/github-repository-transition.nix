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
  # repository: the control plane's egress names no host, so what it grants is
  # public HTTPS with this site's own networks taken out of it. Every arm that
  # reaches GitHub -- the ticket service's, the finalizer's and the importer's,
  # each of which now mints there -- carries every exception, and an arm that
  # lost one would reach a private address on the strength of a rule written for
  # the internet.
  network="$root/cluster/apps/chuggy-control-plane-network-policy.yaml"
  test "$(grep -c 'cidr: 0.0.0.0/0' "$network")" -ge 3
  for range in 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16; do
    test "$(grep -c -- "- $range" "$network")" -ge 3
  done

  touch "$out"
''
