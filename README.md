# foonf-autopost

Posts a queue of poster images to Instagram on a schedule (Tuesdays and Fridays at 10:00), so a small
Etsy shop gets steady social content without anyone posting by hand. Built for the Foonf shop, but
nothing in the code is specific to it.

Python standard library only. macOS only, because it uses `sips` for image conversion and `launchd`
for scheduling.

## How it works

```
queue.json ─► post.py ─► sips: fit to 1080x1350 (4:5), no cropping
                      ─► gh CLI: host the JPEG in a public GitHub repo (Instagram needs a public image URL)
                      ─► Instagram Graph API: create media container ─► publish
                      ─► mark the entry "posted" in queue.json, append to posted.json
```

- **`post.py`** publishes one post. Dry run is the default; nothing is uploaded or posted unless you
  pass `--live`.
- **`refresh_token.py`** refreshes the 60-day Instagram token. A daily launchd job runs it with
  `--if-due`, so it only refreshes every 45 days, even if the Mac was asleep on the due date.
- **`igcommon.py`** holds the shared helpers: `.env` read and atomic write (mode 600), the Graph API
  call, and token redaction.
- **`install_post_job.sh`** and **`install_launchd.sh`** install the two LaunchAgents.

## Safety design

- **Nothing posts unless a human approved it.** Only queue entries with `"status": "approved"` can be
  published. The scheduled job posts at most one entry per run.
- **No double posts.** Every image is fingerprinted with SHA-256 and checked against `posted.json`;
  reposting needs an explicit `--force`.
- **Validates before posting.** It checks Instagram's aspect-ratio range (0.80 to 1.91) and 8 MB
  limit and refuses to go live if either fails.
- **The token never reaches output.** Every error message passes through a redactor, and the token is
  sent in the request body or query, never printed.
- **Secrets stay out of the repo.** `.env`, `.token_state.json`, the real queue, and the post log are
  all in `.gitignore`.

## Setup

1. Create an Instagram app with Instagram Login and get a long-lived access token and your user ID.
2. `cp .env.example .env` and fill in both values.
3. Install and sign in to the GitHub CLI: `gh auth login`.
4. `cp queue.example.json queue.json`, put your images in `posters/`, and edit the entries.

```bash
python3 post.py --queue Example          # dry run, safe
python3 post.py --queue Example --live   # publish for real
sh install_post_job.sh                   # schedule Tue + Fri 10:00
sh install_launchd.sh                    # schedule the token refresh
python3 -m unittest discover -s tests    # run the tests
```

The first `--live` run creates a public GitHub repo (default name `foonf-posters`, change it with the
`FOONF_REPO` environment variable) to host the images. To pause the schedule:
`launchctl bootout gui/$(id -u)/com.foonf.ig-post`.

## Limits

- macOS only. Posting needs the Mac to be awake or to wake at run time (launchd runs missed jobs on wake).
- Single image posts only, no carousels or Reels.
- Images live in a public GitHub repo, which is required by the Instagram API but means they are public.

## Built with AI assistance

I defined how it should behave, including the approval gate, the dry-run default, and the dedupe
check, and I run it on the live account. The code was written with Claude Code.
