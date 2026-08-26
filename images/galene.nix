{ pkgs }:

# The Galène image the `meet` workload runs, built from nixpkgs's `galene`
# rather than pulled from Docker Hub.
#
# Docker Hub has no image the project publishes, only community builds -- and
# the one in wide use is pinned to a 2023 release. This repository's rule for
# release workloads is a registry digest with a declared source, and the source
# here is the nixpkgs pin in flake.lock: the same `galene` derivation the
# NixOS module would run, wrapped as an OCI layer. Nothing is fetched at build
# time that flake.lock does not name.
#
# Publishing is the documented port-forward flow (README, "Images, the registry,
# and the order things come up in"):
#
#   nix build .#galene-image
#   kubectl -n chuggy-registry port-forward service/registry 5050:5000 &
#   skopeo copy --dest-tls-verify=false \
#     docker-archive:result docker://localhost:5050/meet/galene:<version>
#   skopeo inspect --tls-verify=false \
#     docker://localhost:5050/meet/galene:<version> --format '{{.Digest}}'
#
# and the digest that prints is what cluster/apps/meet.yaml names. The build
# is reproducible (fixed mtimes, no timestamp), so the same flake.lock yields
# the same layers and the same digest.
#
# No TLS material and no data: the container is told where its config and
# groups are by cluster/apps/meet.yaml, and serves plain HTTP behind Traefik.
# The static client is baked in from the derivation's `static` output so the
# manifest never has to name a store path.

let
  galene = pkgs.galene;
in
pkgs.dockerTools.buildLayeredImage {
  name = "registry.chuggy.internal/meet/galene";
  tag = galene.version;

  contents = [ galene galene.static ];

  config = {
    # An unprivileged user the manifest repeats as runAsUser; the image carries
    # no /etc/passwd, so it is numeric here and there.
    User = "10000:10000";
    Entrypoint = [ "${galene}/bin/galene" "-static" "${galene.static}/static" ];
    ExposedPorts = { "8443/tcp" = { }; };
    WorkingDir = "/";
  };
}
