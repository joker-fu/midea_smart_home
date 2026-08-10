#!/usr/bin/env bash
# Resolve the remote name for a given git URL across PCs (the remote may be
# named `cy`, `upstream`, or anything else on different clones).
#
# Usage:
#   resolve_remote.sh <url-substring>
#
# Prints the first remote name whose fetch URL contains the substring, then
# exits 0. Prints nothing and exits 1 if no remote matches.
#
# Example:
#   $ UP=$(./resolve_remote.sh Cyborg2017/midea_smart_home)
#   $ echo "$UP"   # -> cy   (or upstream, etc. depending on the clone)
#
# Matching is on the URL substring so it works regardless of
# https vs ssh, trailing .git, etc.

set -u

needle="${1:-}"
if [ -z "$needle" ]; then
  echo "usage: resolve_remote.sh <url-substring>" >&2
  exit 2
fi

# `git remote -v` prints lines like:
#   cy\thttps://github.com/Cyborg2017/midea_smart_home.git (fetch)
# We want the first column whose URL contains the needle. The awk prints the
# name and exits 0 on match; if no line matched, awk exits 1, which propagates.
git remote -v | awk -v needle="$needle" '
  $0 ~ needle && $NF == "(fetch)" {
    print $1
    found = 1
    exit
  }
  END { if (!found) exit 1 }
'
