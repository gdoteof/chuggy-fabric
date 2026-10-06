#!/bin/sh
# What a release run tells chuggy of itself: one report for each task that
# ended, posted to the address of the action that task is.
#
# The one step of `report-actions` runs this, after every task of the run.
#
# IT ENDS 0 WHATEVER HAPPENED. A report is a record of a release and no part
# of one, and it is sent after the release is published. A step that failed
# here would fail a run that had published, and the trigger builds a failed
# run again. So a report chuggy does not take, a server that is not there and
# a mistake in this file are each a line in the log and the end of it. What
# this file has no say over -- a pod that never starts, a step that is killed
# -- release-pipeline.yaml answers on the task.
#
# A TASK THAT DID NOT END IS NOT REPORTED. A task ends `Succeeded` or
# `Failed`, which are the two outcomes chuggy reads. One that was never
# started, because another failed first, is `None`, and nothing is said of it.
#
# THE BEARER GOES FROM ITS FILE TO curl AND IS NOWHERE ELSE. It is piped: a
# variable of this shell, an argument and the environment are each somewhere
# the process table or a trace shows it. curl is given no `--verbose`, and
# what it prints of a failure names no header. An answer is somebody else's
# bytes, so none of it is printed: the status is, and of a 200 one of the
# three words chuggy answers with. curl speaks https alone and follows no
# redirect, so the bearer is sent to the one host and encrypted.
#
# NO BEARER IS NO REPORT. The Secret is mounted as optional, so a cluster
# whose host has not made it yet runs releases all the same, and this says
# once that it has nobody to report as.
#
# EVERY REPORT IS BOUNDED, so the step is. An attempt has its limit; a refused
# connection, a silence and the statuses curl calls transient are tried again,
# a set number of times; and the limit on the retries is what holds a
# `Retry-After` to less than its server asks for. Of chuggy's answers that
# leaves one sent again, the 503 of a row that could not be written. A 404 is
# a bearer or an action chuggy does not know, a 422 a report it cannot read,
# and neither changes by asking twice.
set -u
trap 'exit 0' EXIT

say() {
  echo "report: $*"
}

: "${ACTIONS:?}" "${COMMIT:?}" "${DETAIL:?}" "${LINK:?}" "${STATUSES:?}" "${BEARER:?}" "${ANSWER:?}"

# Each is written into a JSON string or an address as it stands, so each is
# held to characters that mean nothing in either.
case $COMMIT in
  *[!0-9a-f]*) say "$COMMIT is not a commit hash, so nothing is reported"; exit ;;
esac
[ "${#COMMIT}" -eq 40 ] || { say "$COMMIT is not a full commit hash, so nothing is reported"; exit; }
case $DETAIL in
  *[!A-Za-z0-9._-]*) say "the detail is not a run's name, so nothing is reported"; exit ;;
esac
case $ACTIONS$LINK in
  *[!A-Za-z0-9:/?=\&%._~-]*) say "an address holds a character that is not an address's, so nothing is reported"; exit ;;
esac

if [ ! -e "$BEARER" ]; then
  say "no bearer is mounted at $BEARER, so nothing is reported"
  exit
fi
if [ ! -r "$BEARER" ]; then
  say "the bearer at $BEARER is not this user's to read, so nothing is reported"
  exit
fi
if [ "$(tr -d ' \t\r\n' < "$BEARER" | wc -c)" -eq 0 ]; then
  say "the bearer at $BEARER is empty, so nothing is reported"
  exit
fi

# One report. The bearer is what its file holds without its blanks, which is
# what chuggy reads of its own copy.
report() {
  action=$1 outcome=$2
  body="{\"version\":1,\"commit\":\"$COMMIT\",\"outcome\":\"$outcome\",\"detail\":\"$DETAIL\",\"link\":\"$LINK\"}"
  rm -f "$ANSWER"
  status=$(
    {
      printf 'Authorization: Bearer '
      tr -d ' \t\r\n' < "$BEARER"
      echo
    } | curl --silent --show-error --proto '=https' \
      --max-time 10 --retry 2 --retry-all-errors --retry-max-time 25 \
      --header @- --header 'Content-Type: application/json' --data "$body" \
      --output "$ANSWER" --write-out '%{http_code}' \
      "$ACTIONS/$action/reports"
  )
  ended=$?
  if [ "$ended" -ne 0 ]; then
    say "$action $outcome: not delivered, curl ended $ended"
    return
  fi
  case $status in
    200)
      for word in Recorded Repeated Ignored; do
        if grep -q "\"report\" *: *\"$word\"" "$ANSWER" 2>/dev/null; then
          say "$action $outcome: $word"
          return
        fi
      done
      say "$action $outcome: 200, with an answer this does not know"
      ;;
    *) say "$action $outcome: $status, not recorded" ;;
  esac
}

echo "$STATUSES" | while read -r action status rest; do
  case $action in
    '') continue ;;
    *[!A-Za-z0-9._-]* | [._-]* | *[._-]) say "an action's name is not one chuggy admits, so it is not reported"; continue ;;
  esac
  case $status in
    Succeeded | Failed) report "$action" "$status" ;;
    *) say "$action $status: not a task that ended, so not reported" ;;
  esac
done
