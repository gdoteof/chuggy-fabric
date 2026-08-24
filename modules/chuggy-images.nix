{ config, pkgs, lib, ... }:

# Getting bootstrap and legacy chuggy images onto this node before a registry
# can serve them.
#
# The registry itself must start from an upstream image before anything can be
# pushed into it. Air-gap import remains the recovery path for that bootstrap
# and the delivery path for workloads that still carry `chuggy.invalid` refs.
#
# WHAT MAKES THE ORDERING WORK is k3s's own airgap directory, not a unit here.
# k3s imports every archive under the images directory into containerd as the
# agent starts, which is before the kubelet can schedule a pod that references
# one. A systemd unit ordered After=k3s.service could not make that guarantee --
# it would race the first pod -- and a unit ordered Before=k3s.service would run
# while containerd is down.
#
#   k3s starts -> containerd imports these archives -> auto-deploy applies
#   Flux -> Flux reconciles cluster/apps -> workloads pull `IfNotPresent` and
#   find the image already there
#
# So this module's whole job at boot is to make sure the directory exists with
# the right permissions and is not on a filesystem that gets cleared. The
# command below is for the other case: adding an image to a node that is already
# running, where waiting for a k3s restart would restart every workload on the
# box.
#
# NOT services.k3s.images. That option takes derivations and links them out of
# the Nix store, which is right for an image Nix builds. These are built by
# Docker in kasofsk/chuggy, so there is no derivation to name -- and putting a
# tarball into the store would make this flake's closure depend on bytes nothing
# in it can reproduce.
#
# NOTHING REPLICATES THESE ARCHIVES. Registry-backed images have a declared
# source; an archive here remains node-local bootstrap material.
#
# AND NOTHING DECLARES THEM. The chain above starts from whatever the box
# happens to hold: no option names the archives a host needs, and nothing checks
# that the directory has any. A fresh adopter therefore gets an empty directory
# and legacy workloads in ImagePullBackOff against a registry that does not exist,
# which reads as a broken cluster. Declaring them means naming images built by
# Docker in another repository, at a commit this flake cannot see -- so the
# input that would make the check possible is the thing that is missing, and it
# is missing here rather than hidden.

let
  cfg = config.chuggy.images;

  import' = pkgs.writeShellApplication {
    name = "chuggy-import-image";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      if [ "$#" -ne 1 ]; then
        echo "usage: chuggy-import-image <archive.tar>" >&2
        echo "  Installs the archive into ${cfg.archiveDir} and imports it into containerd now." >&2
        exit 64
      fi

      src="$1"
      if [ ! -s "$src" ]; then
        echo "chuggy-import-image: $src is missing or empty." >&2
        exit 2
      fi

      name="$(basename "$src")"
      case "$name" in
        *.tar) ;;
        *) echo "chuggy-import-image: $name is not a .tar; k3s only reads archives by that suffix." >&2
           exit 64 ;;
      esac

      install -d -m 0700 -o root -g root "${cfg.archiveDir}"

      # Install first, import second. If the import fails the archive is still
      # in place, so the next k3s start retries it; the reverse order would
      # leave an image in containerd that a fresh boot forgets.
      install -m 0600 -o root -g root "$src" "${cfg.archiveDir}/$name"

      if [ ! -S /run/k3s/containerd/containerd.sock ]; then
        echo "chuggy-import-image: containerd is not running; $name is staged and will be" >&2
        echo "  imported the next time k3s starts." >&2
        exit 2
      fi

      # Importing the same archive twice is a no-op: containerd is
      # content-addressed, so a second import re-resolves the same digests.
      ${config.services.k3s.package}/bin/k3s ctr images import "${cfg.archiveDir}/$name"
    '';
  };
in
{
  options.chuggy.images = {
    enable = lib.mkEnableOption "local bootstrap image delivery for chuggy";

    archiveDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/rancher/k3s/agent/images";
      description = ''
        Directory k3s imports container image archives from at agent startup.

        The default is k3s's own path, which is what makes the import happen
        before any pod is scheduled. An adopter who moves it gets a staging
        directory and the command below, and loses the boot-time import -- so
        move it only alongside k3s's own data root.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    # Not a tmpfiles `D`, and not on /tmp: an archive removed between boots is
    # an image the node no longer has, and the pod that wanted it fails with
    # ImagePullBackOff against a registry that does not exist.
    systemd.tmpfiles.rules = [
      "d ${cfg.archiveDir} 0700 root root -"
    ];

    environment.systemPackages = [ import' ];
  };
}
