#!/bin/sh
# Uploads each file named on the command line to the R2 bucket R2_BUCKET of the account CLOUDFLARE_ACCOUNT_ID,
# under <repository>/<UTC time>/, reads the size back, and then fails when the bucket holds more than 4.5 GiB.
# A missing or empty setting fails the job, so a backup never stops without a red run. Both repositories have
# this file, byte for byte; docs/backup.md in fshy.ajam.dev describes the bucket and the restore. The keys come
# from the environment and never go on a command line.
set -eu
for v in CLOUDFLARE_ACCOUNT_ID R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY GITHUB_REPOSITORY; do
  eval "test -n \"\${$v:-}\"" || { echo "the setting $v is missing or empty; docs/backup.md lists them" >&2; exit 1; }
done
R2="https://$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com/$R2_BUCKET"
LIMIT=4831838208

r2() {
  printf 'user = "%s:%s"\naws-sigv4 = "aws:amz:auto:s3"\n' "$R2_ACCESS_KEY_ID" "$R2_SECRET_ACCESS_KEY" |
    curl -sS --fail-with-body --retry 3 -K - "$@"
}

prefix="${GITHUB_REPOSITORY#*/}/$(date -u +%Y-%m-%dT%H%M%SZ)"
for f in "$@"; do
  name=$(basename "$f")
  size=$(wc -c < "$f" | tr -d ' ')
  sum=$(sha256sum < "$f" | cut -d ' ' -f 1)
  r2 -X PUT -H "x-amz-meta-sha256: $sum" --upload-file "$f" "$R2/$prefix/$name" > /dev/null
  got=$(r2 -I "$R2/$prefix/$name" | tr -d '\r' | awk -F': ' 'tolower($1) == "content-length" { print $2 }')
  if [ "$got" != "$size" ]; then
    echo "$prefix/$name: the bucket has '$got' bytes, the file has $size" >&2
    exit 1
  fi
  echo "$prefix/$name: $size bytes, sha256 $sum"
done

list=$(mktemp)
r2 "$R2?list-type=2" > "$list"
python3 - "$LIMIT" "$list" <<'EOF'
import sys
import xml.etree.ElementTree as ET

limit, root = int(sys.argv[1]), ET.parse(sys.argv[2]).getroot()
ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
if root.findtext(ns + "IsTruncated") == "true":
    sys.exit("the bucket lists more than 1,000 files: check it by hand, as docs/backup.md says")
sizes = [int(c.findtext(ns + "Size")) for c in root.iter(ns + "Contents")]
print("the bucket holds %d files, %.2f GiB; the budget is 5 GiB" % (len(sizes), sum(sizes) / 2 ** 30))
if sum(sizes) > limit:
    sys.exit("the bucket holds more than 4.5 GiB: shorten the lifecycle rule, as docs/backup.md says")
EOF
