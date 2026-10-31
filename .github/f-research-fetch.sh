#!/bin/sh
# Fetches the private repository Azathothas/f-research into ./f-research for the workflow f-research-ci, quietly: the
# log of this public repository shows no branch name, tag or commit subject of it. The read-only deploy key comes in
# the environment variable KEY; it is written to a file only the runner user can read, used for one fetch and deleted
# before any code of f-research runs. GitHub's host key is pinned here (docs.github.com, "GitHub's SSH key
# fingerprints"), so the fetch trusts no key that a network path offers.
#
# usage: sh .github/f-research-fetch.sh head|main|all
#   head  every branch, then a detached checkout of $SHA; $SHA and $BASE must be commits of 40 hex digits on a branch
#   main  every branch, then a detached checkout of main
#   all   every branch and tag, for the bundle, with no checkout
set -eu
mode=${1:?usage: f-research-fetch.sh head|main|all}
: "${KEY:?the deploy key is missing: the secret F_RESEARCH_DEPLOY_KEY of this job's environment}"
if [ "$mode" = head ]; then
  printf '%s\n' "${SHA:-}" | grep -qxE '[0-9a-f]{40}' && printf '%s\n' "${BASE:-}" | grep -qxE '[0-9a-f]{40}' ||
    { echo "FAIL inputs (sha and base must each be a commit of 40 hex digits)"; exit 1; }
fi
t=$(cygpath -u "$RUNNER_TEMP" 2>/dev/null || printf '%s' "$RUNNER_TEMP")
k="$t/f-research-key"
h="$t/f-research-known-hosts"
umask 077
trap 'rm -f "$k"' EXIT
printf '%s\n' "$KEY" > "$k"
printf '%s\n' 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' > "$h"
export GIT_SSH_COMMAND="ssh -i $k -o IdentitiesOnly=yes -o UserKnownHostsFile=$h -o StrictHostKeyChecking=yes"
git init -q f-research
git -C f-research remote add origin git@github.com:Azathothas/f-research.git
specs='+refs/heads/*:refs/remotes/origin/*'
[ "$mode" = all ] && specs="$specs +refs/tags/*:refs/tags/*"
ok=0
# shellcheck disable=SC2086
git -C f-research fetch -q --no-tags origin $specs > /dev/null 2>&1 && ok=1
rm -f "$k"
unset GIT_SSH_COMMAND KEY
[ "$ok" = 1 ] || { echo "FAIL fetch (the deploy key, the host key or the network)"; exit 1; }
case $mode in
  head)
    for c in "$SHA" "$BASE"; do
      git -C f-research cat-file -e "$c^{commit}" 2> /dev/null || { echo "FAIL fetch (a commit is on no branch)"; exit 1; }
    done
    git -C f-research checkout -q --detach "$SHA" > /dev/null 2>&1
    ;;
  main)
    git -C f-research checkout -q --detach refs/remotes/origin/main > /dev/null 2>&1
    ;;
esac
echo "fetched f-research ($mode); the key file is deleted"
