{ config, pkgs, lib, ... }:

# What one unit of chuggy work is allowed to cost on this machine.
#
# NONE OF THESE HAVE DEFAULTS, and that is the entire content of this module.
# A safe value depends on how much CPU, memory and disk the adopting box has and
# on what else it is doing, and both ways of guessing are wrong in a way that is
# hard to see: guess low and work cannot complete, guess high and the control
# plane and PostgreSQL are starved by a single task. Neither shows up as a
# missing setting. They show up as a rig that half works.
#
# So an enabled configuration that omits one refuses to evaluate. That refusal
# is what this module is for -- the alternative is a second host that builds
# clean and is not actually supported.
#
# WHAT READS THESE: nothing on the machine, yet. Worker admission, requests,
# limits and the ephemeral workspace bound are Kubernetes objects, and the
# Kubernetes objects are cluster state. This module states the machine's answer
# and refuses without one; a later stage is what carries it into the cluster.
# Saying so is better than inventing a consumer here, because a value carried
# into an object nothing mounts would look like the work was done.
#
# ONE VALUE, NOT TWO. When the scheduler's concurrency bound and Kubernetes'
# capacity policy come from separate settings they disagree eventually, and the
# disagreement is invisible until a second worker is admitted onto a box sized
# for one.

let
  cfg = config.chuggy.work;

  required = [
    { name = "cpu"; value = cfg.worker.cpu; }
    { name = "memory"; value = cfg.worker.memory; }
    { name = "ephemeralStorage"; value = cfg.worker.ephemeralStorage; }
  ];
in
{
  options.chuggy.work = {
    enable = lib.mkEnableOption "chuggy work execution on this host";

    concurrency = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1;
      description = ''
        How many work pods may run at once. One by default: contention on a
        small single-node box is otherwise unpredictable, and this is the rig
        that also holds the control plane and the database.

        Raising it is a decision about this machine, made here. It is not a
        project or ticket input, and nothing chuggy executes can change it.
      '';
    };

    worker = {
      cpu = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "2";
        description = ''
          CPU a single work pod may have, in Kubernetes quantity notation.
          Required.
        '';
      };

      memory = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "4Gi";
        description = ''
          Memory a single work pod may have, in Kubernetes quantity notation.
          Required.
        '';
      };

      ephemeralStorage = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "20Gi";
        description = ''
          Bound on a work pod's writable workspace, in Kubernetes quantity
          notation. Required.

          It is a bound on something that does not survive the pod: a checkout
          is reconstructed from git and declared artifacts, never from a
          previous attempt's filesystem. What this number protects is the node's
          root filesystem, which is the same filesystem everything else on this
          box writes to.
        '';
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = map
      (r: {
        assertion = r.value != null;
        message = ''
          chuggy.work.enable is on but chuggy.work.worker.${r.name} is unset.
          State what one work pod may take from this machine; there is no
          default that is safe on an unknown host.
        '';
      })
      required;
  };
}
