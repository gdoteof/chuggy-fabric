#!/bin/sh
# The BuildKit daemon on the Mac that builds the linux/arm64 half of a
# `build-two-platform-image` run, and the certificates that daemon and the
# run's pod speak to each other with.
#
#   arm64-builder.sh certificates DIRECTORY ADDRESS
#   arm64-builder.sh start
#
# NOTHING IN THE CLUSTER RUNS THIS. An operator runs `certificates` wherever
# openssl is, and `start` on the Mac as the user that runs Colima. `start`
# reads nothing but the files below, and finds Homebrew's docker when the
# shell it is given does not, so it can be sent there on its standard input,
# `ssh <mac> sh -s start < cluster/build-system/arm64-builder.sh`.
#
# NATIVE, ON THE MAC. A Task's pods run on the cluster's nodes, and an arm64
# build on an amd64 node is an emulated one. The build step drives this daemon
# as a client: it sends the commit's tree, and the daemon sends the image back
# as an OCI archive.
#
# THE MAC NEVER PUSHES, AND HOLDS NO REGISTRY CREDENTIAL. The cluster's
# `registry` is the one a build writes, and the Mac does not reach it;
# `registry-public` serves the same store read-only. The pod pushes what came
# back.
#
# MUTUAL TLS, ON ONE PORT. The daemon listens on PORT, with TLS, and on
# nothing else, and refuses a client whose certificate the set's CA did not
# sign. Colima forwards a port a container publishes to every address the Mac
# has, so the port is open to the LAN and the certificate is what admits.
#
# WHAT A BUILD HERE REACHES. A RUN on this daemon leaves the Mac through
# Colima's NAT as the Mac's own address on the LAN, as the runner's job
# containers do. That is the address cluster/apps/vm-registry.yaml admits
# writes from, with no authentication, and the cluster's own builds are kept
# off the LAN by cluster/build-system/platform.yaml. The client's key is what
# admits a build here; two-platform-image.yaml says who can read it.
#
# Every client shares the daemon's one cache, and buildkitd.toml below
# restricts none of it: what a build loads from a cache its client imports is
# kept under the same keys, so a later build can take a step's result from
# what an earlier client sent. And as the daemon is privileged, a RUN that
# escapes its sandbox here is root in Colima's VM, beside the runner's job
# containers.
#
# THE SET IS MADE WHOLE, AND THE CA'S KEY IS NEVER KEPT. `certificates` writes,
# into a DIRECTORY it creates: the CA's certificate, the daemon's certificate
# for ADDRESS -- the Mac's address, as the run names the daemon -- and its key,
# and the client's certificate and key. The CA's key signs the two in a
# directory of its own and is deleted on the way out, an interrupted run's
# included, so nothing signs a third. Installing a set, the first or a
# rotation's, is:
#
#   1. `arm64-builder.sh certificates DIRECTORY ADDRESS`
#   2. ca.crt, server.crt and server.key into TLS below, on the Mac, the key at
#      mode 0600; then `start`, which runs the daemon afresh on them.
#   3. The client's half into the Secret the Task mounts:
#        kubectl -n chuggy-build delete secret arm64-builder-client --ignore-not-found
#        kubectl -n chuggy-build create secret generic arm64-builder-client \
#          --from-file=ca.crt=DIRECTORY/ca.crt \
#          --from-file=tls.crt=DIRECTORY/client.crt \
#          --from-file=tls.key=DIRECTORY/client.key
#   4. `rm -r DIRECTORY`.
#
# ROOTFUL, SO PRIVILEGED. The cluster's builds run rootless BuildKit, and the
# rootless image does not start in Colima's VM: its Ubuntu has AppArmor refuse
# an unconfined process the user namespace RootlessKit makes, and docker's own
# profile refuses RootlessKit's mounts. What would let it is an AppArmor
# profile in the VM that permits both, which is a change to the VM's security
# and not this file's to make. A rootful daemon needs root's mounts and
# namespaces, which docker gives a container only as `--privileged`; it keeps
# BuildKit's sandbox for each RUN, which the cluster's rootless one goes
# without.
#
# ITS CACHE IS ITS OWN, ON A VOLUME, AND BOUNDED. The daemon's state is the
# volume `chuggy-buildkitd`, which outlives the container. It is on the disk
# Colima's docker keeps everything on, beside the runner's images and jobs, so
# the collector holds the cache under `maxUsedSpace` and gives it back down to
# `reservedSpace` while less than `minFreeSpace` is free: the cache goes before
# the runner's own disk floor is reached, and the runner never has to remove
# what it cannot see.
#
# RESTARTED WITH THE VM. `unless-stopped`: docker starts it each time Colima
# starts docker, and a `docker stop` stays stopped.
#
# THE CLIENT'S VERSION. The build step's buildctl is moby/buildkit's rootless
# image in release-pipeline.yaml, and the daemon is the rootful image of the
# same version, pinned by the digest of its index; docker on the Mac takes the
# index's linux/arm64. tests/arm64-builder.py holds the two to one version.
set -eu

PORT=1234
IMAGE=moby/buildkit:v0.26.2@sha256:de10faf919fc71ba4eb1dd7bd6449566d012b0c9436b1c61bfee21d621b009aa
NAME=chuggy-buildkitd
CONFIG="$HOME/Library/Application Support/chuggy-buildkitd"
TLS="$CONFIG/tls"
# How long the set is valid for, in days. A rotation makes a new one.
DAYS=1095

refuse() {
  echo "arm64-builder: $*" >&2
  exit 1
}

# One certificate signed by the CA in $ca: its key and certificate under NAME
# in DIRECTORY, for the extended key usage and the extensions given.
signed() {
  openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$directory/$1.key" -out "$ca/$1.csr" -subj "/CN=$2" 2>/dev/null
  printf '%s\n' "basicConstraints = critical, CA:FALSE" \
    "keyUsage = critical, digitalSignature" "extendedKeyUsage = $3" "$4" > "$ca/$1.ext"
  openssl x509 -req -in "$ca/$1.csr" -CA "$directory/ca.crt" -CAkey "$ca/ca.key" \
    -set_serial "0x$(openssl rand -hex 16)" -days "$DAYS" -extfile "$ca/$1.ext" \
    -out "$directory/$1.crt" 2>/dev/null
}

certificates() {
  [ "$#" -eq 2 ] || refuse "usage: arm64-builder.sh certificates DIRECTORY ADDRESS"
  directory=$1
  address=$2
  command -v openssl >/dev/null 2>&1 || refuse "openssl is not on PATH"
  printf '%s' "$address" | grep -Eqx '([0-9]{1,3}[.]){3}[0-9]{1,3}' ||
    refuse "$address is not an IPv4 address"
  [ ! -e "$directory" ] || refuse "$directory exists, and a set is written whole into a new directory"
  umask 077
  mkdir -p "$directory"
  ca=$(mktemp -d)
  trap 'rm -rf "$ca"' EXIT
  trap 'exit 1' INT TERM HUP
  openssl req -x509 -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$ca/ca.key" -out "$directory/ca.crt" -days "$DAYS" \
    -subj "/CN=chuggy arm64 builder CA" \
    -addext "basicConstraints = critical, CA:TRUE" \
    -addext "keyUsage = critical, keyCertSign, cRLSign" 2>/dev/null
  signed server "chuggy arm64 builder" serverAuth "subjectAltName = IP:$address"
  signed client "chuggy build pod" clientAuth ""
  echo "arm64-builder: a set for $address is in $directory"
}

start() {
  [ "$#" -eq 0 ] || refuse "usage: arm64-builder.sh start"
  command -v docker >/dev/null 2>&1 || PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
  command -v docker >/dev/null 2>&1 || refuse "docker is not on PATH, nor where Homebrew puts it"
  for file in ca.crt server.crt server.key; do
    [ -f "$TLS/$file" ] || refuse "$TLS/$file is not there"
  done
  [ -n "$(find "$TLS/server.key" -perm 0600)" ] || refuse "$TLS/server.key is not at mode 0600"

  cat > "$CONFIG/buildkitd.toml" <<EOF
[grpc]
  address = ["tcp://0.0.0.0:$PORT"]
  [grpc.tls]
    cert = "/etc/buildkit/tls/server.crt"
    key = "/etc/buildkit/tls/server.key"
    ca = "/etc/buildkit/tls/ca.crt"

[worker.oci]
  gc = true
  reservedSpace = "10GB"
  maxUsedSpace = "40GB"
  minFreeSpace = "30GB"
EOF

  docker rm --force "$NAME" >/dev/null 2>&1 || true
  docker run --detach --name "$NAME" --restart unless-stopped --privileged \
    --publish "$PORT:$PORT" \
    --mount "type=volume,source=$NAME,target=/var/lib/buildkit" \
    --mount "type=bind,source=$CONFIG,target=/etc/buildkit,readonly" \
    "$IMAGE" >/dev/null

  tries=60
  until docker logs "$NAME" 2>&1 | grep -q "running server on \[::\]:$PORT"; do
    tries=$((tries - 1))
    if [ "$tries" -eq 0 ] || [ "$(docker inspect --format '{{.State.Running}}' "$NAME")" != true ]; then
      docker logs "$NAME" >&2 || true
      refuse "the daemon is not listening on $PORT"
    fi
    sleep 1
  done
  echo "arm64-builder: $NAME listens on $PORT"
}

case ${1:-} in
  certificates) shift; certificates "$@" ;;
  start) shift; start "$@" ;;
  *) refuse "usage: arm64-builder.sh certificates DIRECTORY ADDRESS | start" ;;
esac
