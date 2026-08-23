{ config, pkgs, lib, ... }:

# The host directories chuggy's data lives in, and nothing else.
#
# Two properties make a directory belong here rather than in a Kubernetes
# volumeClaimTemplate. It has to outlive the object that mounts it -- deleting a
# claim must not delete the data -- and its ownership has to be decided by
# someone who knows the host, because the pod that writes it runs as a numeric
# uid with no account behind it. Both are the machine's business.
#
# So this module creates directories and sets their ownership. It does not
# create the PersistentVolume that binds one into the cluster; that object is
# cluster state and belongs in cluster/apps/, which does not yet hold one. The
# split is deliberate and is the one place the two layers touch a single
# resource: NixOS owns the bytes on disk, Flux owns the object that names them,
# and each can be read without the other.
#
# WHAT PRESERVES THESE ACROSS A REBUILD AND A REBOOT is systemd-tmpfiles `d`,
# which creates a directory when it is absent and adjusts its mode and owner
# when it is not. It never touches contents. `D` would empty the directory on
# every boot and is the one letter between this file and losing the artifacts;
# `d` is not a typo for it.
#
# D23 NAMES TWO RETAINED PATHS AND THIS MODULE SUPPLIES ONE. PostgreSQL's data
# is a dynamically provisioned local-path claim declared in cluster/apps/, so
# there is no host directory here to declare and an option that named one would
# name a directory nothing mounts. The cluster-layer volume comes first; the
# README says so where the other missing inputs are.
#
# WHAT THIS DOES NOT GIVE YOU: durability. A directory on this box's single
# filesystem survives pod replacement, k3s restarts and reboots, and survives
# nothing about the disk failing. D13 says exactly that and this module is where
# it becomes concrete -- there is no replication here, no snapshot, and no
# off-machine copy.

let
  cfg = config.chuggy.state;
in
{
  options.chuggy.state = {
    enable = lib.mkEnableOption "retained host directories for chuggy";

    directory = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/chuggy";
      description = ''
        Root of this host's chuggy state. Created 0700 root:root -- what lands
        under it is generated credentials and data no other account on the box
        has a reason to read.

        It is an option because an adopter may have put /var/lib on a filesystem
        this data should not share. Moving it moves everything below it.
      '';
    };

    artifacts = {
      path = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "/var/lib/chuggy/artifacts";
        description = ''
          Where completed work's declared artifacts are kept. Required: there is
          no safe guess, because the right answer is whichever filesystem on
          this machine has room for build output and is not the one holding
          /boot.

          NOTHING IN THE CLUSTER MOUNTS THIS YET. What would is a static
          PersistentVolume over this path with `Retain`, so that deleting a
          claim leaves the data here -- and no such object is in cluster/apps/.
          Until one is, this option creates a directory nothing reads, and
          taking it for a durability guarantee is taking one this tree does not
          make. When it lands the two have to name the same path, and nothing
          will check that they do: a mismatch mounts an empty directory and
          reports healthy.
        '';
      };

      user = lib.mkOption {
        type = lib.types.int;
        default = 1000;
        description = ''
          Numeric owner of the artifacts directory, matching the uid the pods
          that read and write it run as. It is a number and not a name on
          purpose: there is no account behind it inside the container, so a name
          would resolve here and nowhere that matters.

          Note what uid 1000 collides with on a NixOS host -- it is the first
          normal user, which on this repository's hosts is the human with a
          shell. That human can therefore read and write the artifacts.
          Deliberate, since they already have passwordless sudo, but it is a
          real consequence of matching the container's uid rather than a
          dedicated one, and a host with a second human user should move this.
        '';
      };

      group = lib.mkOption {
        type = lib.types.int;
        default = 1000;
        description = "Numeric group of the artifacts directory. See `user`.";
      };

      mode = lib.mkOption {
        type = lib.types.str;
        default = "0770";
        description = ''
          Mode of the artifacts directory. Group-writable so a second pod
          identity in the same group can write without being the owner;
          world-nothing, because an artifact is work output and this box's other
          services have no business in it.
        '';
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.artifacts.path != null;
        message = ''
          chuggy.state.enable is on but chuggy.state.artifacts.path is unset.
          Name the directory this host keeps work artifacts in; the module will
          not guess a filesystem for durable data.
        '';
      }
    ];

    systemd.tmpfiles.rules = [
      "d ${cfg.directory} 0700 root root -"
    ] ++ lib.optional (cfg.artifacts.path != null)
      "d ${cfg.artifacts.path} ${cfg.artifacts.mode} ${toString cfg.artifacts.user} ${toString cfg.artifacts.group} -";
  };
}
