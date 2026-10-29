# Backup

Both repositories write a weekly backup to one private Cloudflare R2 bucket. If GitHub or the account goes
away, the bucket keeps the last 52 weeks of each repository.

## What is written

| repository | workflow | files in the bucket |
| --- | --- | --- |
| `fshy.ajam.dev` | [`../.github/workflows/backup.yml`](../.github/workflows/backup.yml), Monday 07:00 UTC | `fshy.ajam.dev/<UTC time>/repo.bundle`, `fshy.ajam.dev/<UTC time>/site-data.tar.gz` |
| `f-research` | `.github/workflows/backup.yml`, Monday 07:30 UTC | `f-research/<UTC time>/repo.bundle` |

- `repo.bundle` is a `git bundle` of every branch and tag.
- `site-data.tar.gz` is `site/dist/data` of a build of `main`: the public store `fshy-public.sqlite.gz`, the
  Worker's copy of the store in `w/`, and `manifest.json`, which gives the SHA-256 of each.
- Each file carries its SHA-256 in the metadata `x-amz-meta-sha256`.

Both workflows call [`../.github/r2-backup.sh`](../.github/r2-backup.sh). The two copies of that script are the
same, byte for byte. Each workflow also runs by hand on `main`.

## The rules of the bucket

| rule | value |
| --- | --- |
| lifecycle | a file is deleted 365 days after it is written; an unfinished upload, after 1 day |
| lock | a file under `fshy.ajam.dev/` or `f-research/` cannot be deleted or replaced for 28 days |
| budget | 5 GiB. The script fails the job when the bucket holds more than 4.5 GiB |
| keys | each repository has its own token, for this bucket only, in `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` |
| settings | `CLOUDFLARE_ACCOUNT_ID` and `R2_BUCKET`. In `fshy.ajam.dev` all four are secrets of the environment `backup`, which only `main` can use, so the public log does not show them. In `f-research`, a private repository, the keys are repository secrets and the two settings are repository variables |

The script fails the job when a setting is missing or empty, so a backup does not stop without a red run.
⚠ GitHub stops the scheduled workflows of a public repository after 60 days with no activity, and such a stop
shows no red run. The 365 days keep the last backups for a year after that. A fork does not run the schedule
unless its owner turns it on.

A week adds about 65 MB (2026-10-29: about 28 MB for `f-research`, 10 to 15 MB for `fshy.ajam.dev`, 22 MB for
the site data), so 52 weeks use about 3.4 GB. The repositories grow, so the budget check can fail within the
year.

**If the budget check fails.** The job log gives the total. Shorten the lifecycle rule in the R2 settings of the
bucket, for example to 182 days, or delete the oldest folders by hand after their 28 days. Do not remove the
lock.

## Restore

You need an R2 token for the bucket with read access, from the Cloudflare dashboard (R2, Manage API tokens).
Its S3 access key ID and secret access key go in a curl config file, never on the command line:

```bash
printf 'user = "%s:%s"\naws-sigv4 = "aws:amz:auto:s3"\n' "$KEY_ID" "$SECRET" > r2.cfg
R2=https://ACCOUNT_ID.r2.cloudflarestorage.com/BUCKET
curl -sS -K r2.cfg "$R2?list-type=2&prefix=f-research/"
curl -sS -K r2.cfg -o repo.bundle "$R2/f-research/TIME/repo.bundle"
sha256sum repo.bundle
git bundle verify repo.bundle
git clone --mirror repo.bundle f-research.git
git -C f-research.git push --mirror NEW_REMOTE_URL
```

Compare the SHA-256 with the `x-amz-meta-sha256` header (`curl -sS -K r2.cfg -I URL`). The mirror clone holds
every branch and tag of the bundle, and `push --mirror` writes all of them to the new remote. Delete `r2.cfg`
after the restore.
