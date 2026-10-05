#!/usr/bin/env bash
# The dump the migration Job takes of the database it is about to migrate.
#
# The `dump` container in chuggy-migrate.yaml runs this after the wait for
# PostgreSQL and before the migration, and the migration starts only if this
# exits 0. So every failure here is a non-zero exit.
#
# A PAIR IS WHOLE OR IT IS NAMED `.partial`. A dump is two files: the archive
# of the `chuggy` database, and the globals -- the roles and their passwords,
# which belong to the server and are in no database's archive. Both are written
# under a name ending in `.partial`, the archive is read back whole, the
# globals are held to the lines `pg_dumpall` ends on, and only then is each
# renamed. The globals are renamed first, so an archive under its final name
# has its globals beside it.
#
# THE READ-BACK READS EVERY BLOCK AND ASKS NO SERVER. `pg_restore` given a file
# to write and no database turns the archive back into SQL, which takes its
# table of contents and all the data behind it, so an archive cut short is
# refused wherever the cut falls. The SQL goes to /dev/null. Nothing runs it:
# this reads that the archive is all there, not that a server would take it.
#
# `pg_dumpall` DOES NOT REPORT A WRITE THAT FAILED. On a volume that fills while
# it writes, it exits 0 over globals that are short or empty. So the file is
# held to the lines `pg_dumpall` ends a dump with, as its own last lines and
# not as lines somewhere in it.
#
# RETENTION RUNS AFTER A DUMP THAT SUCCEEDED, AND ONLY THEN. It keeps the pair
# just written and the newest of the others, CHUG_DUMP_KEEP archives in all,
# and removes every other file this script could have named: the older pairs,
# and what a run that failed left behind. A file named any other way is not
# this script's and is never removed. A run that fails removes nothing, its own
# partial files included.
#
# RETENTION LEAVES A LATER RUN THAT IS STILL WRITING. Two runs share the
# directory when a Job is replaced while its dump is being taken and its pod
# has not yet stopped. So a file stamped no earlier than this run's own is left
# unless its archive was under its final name when this run looked -- that
# rename is a run's last, so an archive without it is a run not yet done. A run
# that started earlier is not told from one that failed: a later run that
# finishes first removes its partial files, and it fails.
#
# WHERE, AND WITH WHAT PASSWORD, IS THE POD'S TO SAY. PGHOST, PGPORT and
# PGPASSWORD are libpq's own variables; the directory, the count and the Job's
# name arrive as CHUG_DUMP_DIR, CHUG_DUMP_KEEP and CHUG_DUMP_JOB. That is what
# lets tests/dump-script.nix run this file, as the pod is given it, against a
# PostgreSQL of its own.
#
# AS `postgres`, AND `-U` IS REQUIRED. The globals carry every role's password,
# which only a superuser reads. The pod's uid has no passwd entry for libpq to
# take a user name from, which chuggy-migrate.yaml argues beside the wait.
set -o errexit -o nounset -o pipefail
umask 077
# The order a glob expands in and `<` compares in, which retention reads as
# age.
export LC_ALL=C

refuse() {
  echo "dump: $1" >&2
  exit 1
}

for variable in PGHOST PGPORT PGPASSWORD CHUG_DUMP_DIR CHUG_DUMP_KEEP CHUG_DUMP_JOB; do
  [ -n "${!variable:-}" ] || refuse "$variable is not set"
done
directory=$CHUG_DUMP_DIR
keep=$CHUG_DUMP_KEEP
job=$CHUG_DUMP_JOB

[[ $keep =~ ^[1-9][0-9]*$ ]] ||
  refuse "CHUG_DUMP_KEEP is '$keep', which is not a count of one or more"
[[ $job =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] ||
  refuse "CHUG_DUMP_JOB is '$job', which is not the name of a Job"

# What this script names, and the whole of what retention may remove: a regular
# file called by a UTC timestamp, then a Job's name, then one of the four
# endings below.
own='^[0-9]{8}T[0-9]{6}Z-[a-z0-9]([a-z0-9-]*[a-z0-9])?$'

name=$(date -u +%Y%m%dT%H%M%SZ)-$job
archive=$directory/$name.dump
globals=$directory/$name.globals.sql
for path in "$archive" "$globals" "$archive.partial" "$globals.partial"; do
  [ ! -e "$path" ] || refuse "$path is already there, and a dump overwrites nothing"
done

pg_dump -w -U postgres -Fc -f "$archive.partial" chuggy
pg_restore -f /dev/null "$archive.partial"
pg_dumpall -w -U postgres --globals-only -f "$globals.partial"
closing=$'--\n-- PostgreSQL database cluster dump complete\n--'
[ "$(tail -n 4 -- "$globals.partial")" = "$closing" ] ||
  refuse "$globals.partial does not end as pg_dumpall ends a dump, so it is not whole"

mv -- "$globals.partial" "$globals"
mv -- "$archive.partial" "$archive"
echo "dump: wrote $archive and $globals"

# The pair just written is kept whatever its place in the order: a clock that
# went backwards between two runs must not make this run remove its own dump.
# Every archive under its final name is noted as well, kept or not, which is
# what the loop after this one tells a finished run from an unfinished one by.
declare -A kept=(["$name"]=1) whole=()
others=$((keep - 1))
shopt -s nullglob
archives=("$directory"/*.dump)
for ((index = ${#archives[@]} - 1; index >= 0; index--)); do
  path=${archives[index]}
  base=${path##*/}
  base=${base%.dump}
  [[ $base =~ $own ]] || continue
  [ -f "$path" ] && [ ! -L "$path" ] || continue
  whole[$base]=1
  [ "$base" != "$name" ] && ((others > 0)) || continue
  kept[$base]=1
  others=$((others - 1))
done

for path in "$directory"/*; do
  file=${path##*/}
  case $file in
    *.dump.partial) base=${file%.dump.partial} ;;
    *.globals.sql.partial) base=${file%.globals.sql.partial} ;;
    *.globals.sql) base=${file%.globals.sql} ;;
    *.dump) base=${file%.dump} ;;
    *) continue ;;
  esac
  [[ $base =~ $own ]] || continue
  [ -z "${kept[$base]:-}" ] || continue
  [[ ${base%%-*} < ${name%%-*} ]] || [ -n "${whole[$base]:-}" ] || continue
  [ -f "$path" ] && [ ! -L "$path" ] || continue
  rm -f -- "$path"
  echo "dump: removed $path"
done
