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
# cluster state and belongs in cluster/apps/. The split is deliberate and is the
# one place the two layers touch a single resource: NixOS owns the bytes on
# disk, Flux owns the object that names them, and each can be read without the
# other.
#
# WHICH SIDE WINS WHERE THEY OVERLAP: this one, for everything about the
# directory itself. A PersistentVolume names a host path; it does not create
# that path and does not set its mode or owner. The options below do, on every
# activation. So a cluster-layer manifest that also states a mode is restating
# this module's answer rather than giving one, and if the two ever say
# different things the next rebuild settles it without reporting that it did.
#
# WHAT PRESERVES THESE ACROSS A REBUILD AND A REBOOT is systemd-tmpfiles `d`,
# which creates a directory when it is absent and adjusts its mode and owner
# when it is not -- including back over a mode something else set in between,
# which is what makes this module the authority above. It never touches
# contents. `D` would empty the directory on every boot and is the one letter
# between this file and losing the artifacts; `d` is not a typo for it.
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

          WHAT MOUNTS IT IS NOT HERE. A static PersistentVolume over this path
          with `Retain` is what binds it into the cluster and what makes
          deleting a claim leave the data behind; that object is cluster state
          and lives in cluster/apps/, on its own release schedule. This option
          creates the directory either way. On a host where no such volume has
          been reconciled it creates one nothing reads, and taking that for a
          durability guarantee is taking one this tree does not make.

          The two have to name the same path and nothing checks that they do: a
          mismatch mounts an empty directory and reports healthy.
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
          shell. So the owner of the artifacts is a person, and no mode on the
          directory changes that.

          WHAT KEEPS THEM OUT IS THE PARENT, NOT THE MODE. `directory` above is
          0700 root:root and path resolution needs execute on every component,
          so uid 1000 cannot traverse into a directory it owns without being
          root. It has passwordless sudo, so it reads the artifacts by being
          root rather than by owning them -- which is deliberate, but is a
          consequence of matching the container's uid rather than using a
          dedicated one. An adopter who points `path` outside `directory` gives
          up that gate and is left with `mode` alone; a host with a second human
          user should move this off 1000 rather than rely on either.
        '';
      };

      group = lib.mkOption {
        type = lib.types.int;
        default = 1000;
        description = "Numeric group of the artifacts directory. See `user`.";
      };

      mode = lib.mkOption {
        type = lib.types.str;
        default = "0750";
        description = ''
          Mode of the artifacts directory, and the only statement of it that
          has an effect. World-nothing, because an artifact is work output and
          this box's other services have no business in it.

          IT WAS 0770, AND THE GROUP WRITE BIT WAS A PERMISSION NOTHING HELD.
          The reason given for it was a second pod identity in the same group
          writing without being the owner, and there is no such identity: the
          reader mounts this read-only, and the writer runs as `user` above,
          which owns the directory -- so the owner bits alone were doing all the
          work. A group write bit granted to a group with no members is not a
          safeguard against a second identity arriving; it is a permission
          already waiting for whoever gets that gid next, on a host where `user`
          is a human account. 0750 costs nothing today, and a second writer that
          genuinely needs to write is a deliberate change to this option rather
          than a default that arrived ahead of the requirement.

          WHO CAN ALREADY READ IT IS NOT A QUESTION THIS SETTLES. `user` is
          1000, which on a NixOS host is the first human account and not a
          dedicated service uid, so the human with a shell owns this directory
          whatever the mode says. Read the note on `user` before concluding that
          tightening this keeps anyone out.

          This is what the directory ends up with. The tmpfiles `d` rule below
          runs on every activation and adjusts the mode of a directory that
          already exists, so a mode set by hand -- or documented elsewhere as a
          property of the volume that mounts this path -- is reset to this one
          at the next rebuild, with nothing reporting the change.
        '';
      };
    };

    registry = {
      path = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "/var/lib/chuggy/registry";
        description = ''
          Filesystem path retained for the in-cluster OCI registry. Required:
          the registry is the source of release images and build artifacts, so
          placing it on an incidental filesystem is not a safe default.

          A static PersistentVolume in cluster/apps/ binds this path. The
          machine layer creates it and owns its mode; the cluster layer mounts
          it and owns its retention policy.
        '';
      };

      user = lib.mkOption {
        type = lib.types.int;
        default = 1000;
        description = "Numeric owner matching the registry container's runtime uid.";
      };

      group = lib.mkOption {
        type = lib.types.int;
        default = 1000;
        description = "Numeric group matching the registry container's runtime gid.";
      };

      mode = lib.mkOption {
        type = lib.types.str;
        default = "0750";
        description = "Mode enforced on the registry storage directory at activation.";
      };
    };

    buildResults = {
      path = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "/var/lib/chuggy/build-results";
        description = ''
          Filesystem path retaining verified build-attempt provenance after
          live BuildRuns are removed. The static PersistentVolume binds this
          path and the machine-layer provenance recorder writes it as root.
        '';
      };

      user = lib.mkOption {
        type = lib.types.int;
        default = 0;
        description = "Numeric owner of retained provenance records.";
      };

      group = lib.mkOption {
        type = lib.types.int;
        default = 0;
        description = "Numeric group of retained provenance records.";
      };

      mode = lib.mkOption {
        type = lib.types.str;
        default = "0700";
        description = "Mode enforced on retained build-result storage at activation.";
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
      {
        assertion = cfg.registry.path != null;
        message = ''
          chuggy.state.enable is on but chuggy.state.registry.path is unset.
          Name the directory this host keeps OCI images and artifacts in; the
          module will not guess a filesystem for retained data.
        '';
      }
    ];

    systemd.tmpfiles.rules = [
      "d ${cfg.directory} 0700 root root -"
    ] ++ lib.optional (cfg.artifacts.path != null)
      "d ${cfg.artifacts.path} ${cfg.artifacts.mode} ${toString cfg.artifacts.user} ${toString cfg.artifacts.group} -"
    ++ lib.optional (cfg.registry.path != null)
      "d ${cfg.registry.path} ${cfg.registry.mode} ${toString cfg.registry.user} ${toString cfg.registry.group} -"
    ++ lib.optional (cfg.buildResults.path != null)
      "d ${cfg.buildResults.path} ${cfg.buildResults.mode} ${toString cfg.buildResults.user} ${toString cfg.buildResults.group} -";
  };
}
