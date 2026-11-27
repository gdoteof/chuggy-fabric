# Whether the tool server asks for the API's audience under the API's issuer
# and algorithms, answers the client the README creates, is probed on its two
# health routes, admits Traefik alone and reaches its three arms alone, and is
# served on a host gtr's tunnel forwards, read off the rendered manifests, the
# hostnames gtr is built with and the README.
#
# The audience, the client and the host are each written in more than one
# file, and each reads correctly alone. The argument for holding each is in
# tool-server.py's own header.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
  said = pkgs.writeText "tool-server-host.json" (builtins.toJSON {
    hostnames = host.config.chuggy.tunnel.hostnames;
  });
in
pkgs.runCommand "chuggy-tool-server" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./tool-server.py} ${rendered}/cluster.yaml ${said} ${../README.md}
  touch "$out"
''
