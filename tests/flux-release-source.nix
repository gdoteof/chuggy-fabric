# What a host's `fabric-release` keeps of this repository, decided from the
# `ignore` in the manifest the host generates rather than from a copy of its
# lines. The argument for each assertion is in flux-release-source.py's own
# header.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-flux-release-source" { nativeBuildInputs = [ python ]; } ''
  python3 ${./flux-release-source.py} \
    ${host.config.services.k3s.manifests.flux-sync.source} ${../.}
  touch "$out"
''
