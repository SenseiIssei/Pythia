# Disk: where the untracked growth goes. Pre-registration

Registered 2026-11-16 and committed before the first run of the breakdown, so before any part's size or growth
below exists. On `_ops/disk/latest.json` of 2026-11-16: 166.7 GB free of 463.9, the free space falling 4.7 to 5.4 GB
a day (30.9 days left); the tracked datasets are 32.7 GB and grow 0.72 GB a day, 264.5 GB are used outside them and
grow 4.5 GB a day. The weekly page printed the tracked growth next to the days left, which hid where the growth is.
Code `lab/ops/jobs.py` (`measure_parts`, called by `measure_disk`, which the hourly health check runs on the host
as root), tests `tests/test_jobs.py` on a fake root folder, a fake docker and a fake history. An inventory, not a
study: it makes no performance number, so no trial goes to R5's registry. It reads only and writes nothing but
`<data>/_ops/disk/parts.jsonl` (the daily history), `<data>/reports/disk/breakdown.md` and `.json`. It deletes,
moves and stops nothing; the owner decides.

## What is measured, once a day (at most every 20 h, at the health check)

- **One walk**: `du -x -B1 --max-depth=4` of the disk's root (`paths.disk_root` of the table, `/` on the server):
  the bytes the disk holds (blocks, not apparent size, so the parts add up to the used space), by folder, on this
  filesystem only. Every folder du could not read is listed with du's reason; a walk past 5 minutes is cut and
  says so.
- **Docker**: `docker system df` splits `var/lib/docker` into images, the containers' writable layers, volumes and
  the build cache; the containers' log files are `var/lib/docker/containers`; what is left of the folder is
  docker's other use. Without docker, or when it fails, docker is one part and the reason is in the report.
- **Files deleted but still open** (a log a process writes after it was removed): the blocks of every such file in
  `/proc/*/fd` on this filesystem, once per inode.
- **Not seen**: the used space (statvfs) minus the walk and the deleted open files: filesystem metadata and what
  could not be read.

## The parts

Named parts by path: docker (as above), containerd, journald (`var/log/journal`), the job logs (`var/log/pythia`),
the other logs (the rest of `var/log`), the research lanes (`opt/pythia-agent`: worktrees, runs, logs), the lanes'
`/out` (`srv/pythia-agent-out`), the lane records (`root/pythia-lanes`), the backups (`srv/pythia-backup`), the code
copies (`opt/pythia-src`, `-lab`, `-live`, `-ops`, `-recorder`), caches outside the data folder (`root/.cache`,
`.npm`, `.cargo`, `.rustup`, `tmp`, `var/tmp`, `var/cache`), the system (`usr`, `boot`, `snap`, `var/lib/snapd`,
`var/lib/apt`) and swap files. The data folder: its tracked datasets as one part, and every top-level folder of it
that is not fully a dataset (`live`, `trials`, `_ops`, ...) as its own part. Every other folder one and two levels
below the root that holds bytes no named part claims is its own part (`other /x/y`), so the parts cover the walk.
The T4 book_depth backfill writes inside the data folder (`book_depth`, a tracked dataset; `PYTHIA_BOOK_DEPTH` is
unset on the server), so it has no part of its own.

## The numbers

- **GB**: the part's bytes in the newest entry.
- **GB a day**: against the oldest entry of the history 1 to 8 days back (as the datasets), None before one exists.
- **Coverage**: the growth a day of the growing named parts (every part but the `other` parts and "not seen") over
  that of every growing untracked part (a part that shrank does not hide growth in another). The judgement: the breakdown names parts covering at least 90 % of the untracked growth,
  or it lists which paths could not be read and why.
- **Who reads it**: for a data folder the readers of `reports/recordings/latest.json` (T13) by its path; for the
  others a fixed line per part (the containers, the deploys, the lanes).
- **Proposal**, one of keep, thin, compress, move, stop (or check for an unknown folder), fixed per named part
  with the command the owner would run; for a data folder T13's proposal or keep when a book or job reads it.

## The page and the health check

- The weekly page's disk line: the free space, its fall a day (the faster of 3 and 7 days, the one `daysLeft` is
  computed from), the days left as `daysLeft` rounded, and the two parts that grow most.
- The health check's disk row turns red under 21 days left (was 14).
