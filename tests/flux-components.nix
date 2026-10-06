# Who the Flux install lets post to notification-controller, and whose fields
# its kustomize-controller is started to take over, read off the manifest the
# host hands k3s rather than off the path it is checked in at: the file a
# rebuild links into the manifests directory and the file this holds cannot
# come apart. The argument for each assertion is in flux-components.py's own
# header.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-flux-components" { nativeBuildInputs = [ python ]; } ''
  python3 ${./flux-components.py} \
    ${host.config.services.k3s.manifests.flux-components.source}
  touch "$out"
''
