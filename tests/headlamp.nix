# Headlamp's release, binding and Ingress, read off the rendered cluster,
# against the authenticator and the tunnel hostnames gtr is built with, and
# against a host that names no authenticator. The argument for each assertion
# is in headlamp.py's own header.
#
# What each host says is handed over from its built configuration rather than
# restated here, so that the flag, the file and the restart trigger this holds
# are the ones k3s is started with.
{ pkgs, host, unauthenticated }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
  path = "rancher/k3s/authentication-config.yaml";
  said = h: pkgs.writeText "headlamp-host.json" (builtins.toJSON {
    flags = h.config.services.k3s.extraFlags;
    file = if h.config.environment.etc ? ${path}
      then h.config.environment.etc.${path}.source
      else null;
    restartTriggers = map toString h.config.systemd.services.k3s.restartTriggers;
    hostnames = h.config.chuggy.tunnel.hostnames;
  });
in
pkgs.runCommand "chuggy-headlamp" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./headlamp.py} ${rendered} ${said host} ${said unauthenticated}
  touch "$out"
''
