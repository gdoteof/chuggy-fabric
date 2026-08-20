{ config, pkgs, lib, ... }:

# Bootstraps Flux from the machine layer, so the cluster populates itself.
#
# k3s applies anything under /var/lib/rancher/k3s/server/manifests at startup,
# and services.k3s.manifests links files there declaratively. So the chain is:
#
#   nixos-rebuild switch -> k3s starts -> k3s applies Flux -> Flux reads the
#   repo -> apps exist
#
# Nobody runs kubectl. A fresh box, or the second dev's box, reaches a populated
# cluster from one command. That is the reproducibility this is for -- not
# elaborate machinery.
#
# Deliberately NOT `flux bootstrap`: that wants a GitHub token with write scope
# so it can push a commit and create a deploy key. The manifests it would commit
# are already in this repo, and the repo is public, so Flux needs no credentials
# at all. Fewer moving parts and nothing to rotate.
#
# Only source-controller and kustomize-controller are installed. helm-controller
# and notification-controller are omitted until something needs them.

let
  cfg = config.chuggy.flux;
in
{
  options.chuggy.flux = {
    enable = lib.mkEnableOption "Flux GitOps reconciliation";
  };

  config = lib.mkIf cfg.enable {
    services.k3s.manifests = {
      # Order matters on a cold start: the CRDs and controllers must exist
      # before the GitRepository and Kustomization that use them. k3s applies
      # these alphabetically, and "components" sorts before "sync" -- which is
      # load-bearing, not a coincidence. If that ever stops holding, the sync
      # objects fail once and k3s retries them, so it self-corrects either way.
      flux-components.source = ../cluster/flux-system/gotk-components.yaml;
      flux-sync.source = ../cluster/flux-system/gotk-sync.yaml;
    };

    # `flux` CLI for inspecting reconciliation: flux get kustomizations, etc.
    environment.systemPackages = [ pkgs.fluxcd ];
  };
}
