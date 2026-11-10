#!/usr/bin/env python3
"""Post a poster JPEG to Instagram (Instagram API with Instagram Login).

The post must be named explicitly, either as an image path or as a queue entry (--queue NAME);
nothing is ever picked automatically. A queue entry in queue.json supplies the image and caption
and must have status "approved". It is marked "posted" only after a successful --live run. The image is fit to
1080x1350 (4:5) without cropping, with black padding added where the aspect ratio differs.

Dry run is the default: converts the image and prints what would be posted, but uploads
nothing and posts nothing. Pass --live to actually host the JPEG on GitHub and publish.

    python3 post.py posters/poster.jpg                      # dry run
    python3 post.py posters/poster.jpg --caption "Hello" --live
    python3 post.py --queue Serenity                        # dry run of a queue entry
    python3 post.py --queue Serenity --live                 # publish it, then mark it posted
    python3 post.py --next --live                           # publish the first approved queue entry (used by the scheduled job)
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from igcommon import HERE, GraphError, graph, load_env, redact

OUT_DIR = os.path.join(HERE, "out")
LOG_PATH = os.path.join(HERE, "posted.json")
QUEUE_PATH = os.path.join(HERE, "queue.json")
REPO_NAME = os.environ.get("FOONF_REPO", "foonf-posters")
TARGET_W, TARGET_H = 1080, 1350  # 4:5
MAX_BYTES = 8 * 1024 * 1024
MIN_RATIO, MAX_RATIO = 4 / 5, 1.91


def load_log():
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            return json.load(f)
    return []


def append_log(entry):
    log = load_log()
    log.append(entry)
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def load_queue():
    if not os.path.exists(QUEUE_PATH):
        sys.exit(f"No queue file at {QUEUE_PATH}")
    with open(QUEUE_PATH) as f:
        return json.load(f)


def save_queue(queue):
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
        f.write("\n")


def find_queue_entry(queue, name):
    matches = [e for e in queue if e["name"].lower() == name.lower()]
    if not matches:
        sys.exit(f"No queue entry named {name!r}. Entries: {', '.join(e['name'] for e in queue)}")
    if len(matches) > 1:
        sys.exit(f"{len(matches)} queue entries are named {name!r}; make the names unique")
    return matches[0]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_size(path):
    out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
                         check=True, capture_output=True, text=True).stdout
    w = int(re.search(r"pixelWidth: (\d+)", out).group(1))
    h = int(re.search(r"pixelHeight: (\d+)", out).group(1))
    return w, h


def to_jpeg(src, digest):
    """Convert with macOS sips: scale to fit inside 1080x1350 (no cropping), pad the rest with black."""
    os.makedirs(OUT_DIR, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.splitext(os.path.basename(src))[0]).strip("-")
    dst = os.path.join(OUT_DIR, f"{stem}-{digest[:10]}.jpg")
    w, h = image_size(src)
    scale = min(TARGET_W / w, TARGET_H / h)
    new_w, new_h = min(TARGET_W, round(w * scale)), min(TARGET_H, round(h * scale))
    subprocess.run(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "90",
         "--resampleHeightWidth", str(new_h), str(new_w),
         "--padToHeightWidth", str(TARGET_H), str(TARGET_W), "--padColor", "000000",
         src, "--out", dst],
        check=True, capture_output=True)
    return dst


def validate_jpeg(path):
    w, h = image_size(path)
    ratio = w / h
    size = os.path.getsize(path)
    problems = []
    if not MIN_RATIO <= ratio <= MAX_RATIO:
        problems.append(f"aspect ratio {ratio:.2f} is outside Instagram's 0.80-1.91 range")
    if size > MAX_BYTES:
        problems.append(f"{size / 1e6:.1f} MB exceeds Instagram's 8 MB limit")
    return w, h, size, problems


# --- GitHub hosting via gh CLI ------------------------------------------------

def gh(*args, input=None):
    r = subprocess.run(["gh", *args], input=input, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def gh_owner():
    if not shutil.which("gh"):
        return None
    try:
        return gh("api", "user", "--jq", ".login")
    except RuntimeError:
        return None


def ensure_repo(owner):
    repo = f"{owner}/{REPO_NAME}"
    try:
        gh("repo", "view", repo, "--json", "name")
    except RuntimeError:
        print(f"Creating public repo {repo}")
        gh("repo", "create", repo, "--public", "--description", "Public JPEG hosting for Instagram posts")
    return repo


def upload_jpeg(repo, jpeg):
    """Upload via the contents API (no local clone). Returns an immutable raw URL pinned to the commit."""
    path = f"posters/{os.path.basename(jpeg)}"
    try:
        sha = gh("api", f"repos/{repo}/commits?path={path}&per_page=1", "--jq", ".[0].sha")
        if sha:
            print(f"Already hosted in {repo}, reusing")
            return f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
    except RuntimeError:
        pass  # empty repo has no commits yet
    with open(jpeg, "rb") as f:
        body = json.dumps({"message": f"Add {os.path.basename(jpeg)}",
                           "content": base64.b64encode(f.read()).decode()})
    sha = gh("api", "-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-",
             "--jq", ".commit.sha", input=body)
    return f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"


def wait_public(url, timeout=60):
    deadline = time.time() + timeout
    while True:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                ctype = r.headers.get("Content-Type", "")
                if not ctype.startswith("image/jpeg"):
                    print(f"Warning: raw URL serves Content-Type {ctype!r}")
                return
        except Exception:
            if time.time() > deadline:
                raise RuntimeError(f"{url} not publicly reachable after {timeout}s")
            time.sleep(3)


# --- Instagram ----------------------------------------------------------------

def check_account(token, user_id):
    me = graph("GET", "me", {"fields": "user_id,username"}, token)
    if user_id not in (str(me.get("user_id")), str(me.get("id"))):
        print(f"Warning: IG_USER_ID does not match the token's account "
              f"(token belongs to user_id {me.get('user_id')})")
    return me.get("username")


def publish(token, user_id, image_url, caption):
    container = graph("POST", f"{user_id}/media", {"image_url": image_url, "caption": caption}, token)["id"]
    print(f"Created media container {container}")
    for _ in range(30):
        status = graph("GET", container, {"fields": "status_code"}, token).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise GraphError(f"container {container} status {status}")
        time.sleep(2)
    else:
        raise GraphError(f"container {container} not ready after 60s")
    media_id = graph("POST", f"{user_id}/media_publish", {"creation_id": container}, token)["id"]
    permalink = graph("GET", media_id, {"fields": "permalink"}, token).get("permalink")
    return media_id, permalink


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", help="JPEG to post (give this or --queue; never auto-picked)")
    ap.add_argument("--queue", metavar="NAME", help="post the queue.json entry with this name (uses its image and caption)")
    ap.add_argument("--next", action="store_true", help="post the first 'approved' entry in queue.json order (for the scheduled job)")
    ap.add_argument("--caption", help="caption text (default: same-named .txt next to the image, else empty)")
    ap.add_argument("--live", action="store_true", help="actually upload and publish (default is dry run)")
    ap.add_argument("--force", action="store_true", help="post even if this image was posted before")
    args = ap.parse_args()

    env = load_env()
    token, user_id = env.get("IG_ACCESS_TOKEN"), env.get("IG_USER_ID")
    if not token or not user_id:
        sys.exit("IG_ACCESS_TOKEN and IG_USER_ID must be set in .env")

    if bool(args.image) + bool(args.queue) + args.next != 1:
        ap.error("give exactly one of: an image path, --queue NAME, or --next")
    if (args.queue or args.next) and args.caption is not None:
        ap.error("--caption can't be combined with --queue/--next (the caption comes from the queue entry)")

    queue = entry = None
    if args.queue or args.next:
        queue = load_queue()
        if args.next:
            entry = next((e for e in queue if e["status"] == "approved"), None)
            if entry is None:
                print("Queue has no approved entries; nothing to post.")
                return
        else:
            entry = find_queue_entry(queue, args.queue)
        if entry["status"] != "approved":
            sys.exit(f"Queue entry {entry['name']!r} has status {entry['status']!r}; only 'approved' entries can be posted")

    log = load_log()
    src = os.path.join(HERE, entry["file"]) if entry else os.path.expanduser(args.image)
    if not os.path.isfile(src):
        sys.exit(f"Not found: {src}")
    digest = sha256(src)
    if any(e["sha256"] == digest for e in log) and not args.force:
        sys.exit(f"{os.path.basename(src)} was already posted (see posted.json); use --force to repost")

    caption = entry["caption"] if entry else args.caption
    if caption is None:
        sidecar = os.path.splitext(src)[0] + ".txt"
        caption = open(sidecar).read().strip() if os.path.exists(sidecar) else ""

    jpeg = to_jpeg(src, digest)
    w, h, size, problems = validate_jpeg(jpeg)
    owner = gh_owner()

    print(f"{'LIVE' if args.live else 'DRY RUN'}")
    if entry:
        print(f"  queue:    {entry['name']} (status {entry['status']})")
    print(f"  source:   {src}")
    print(f"  jpeg:     {jpeg} ({w}x{h}, {size / 1024:.0f} KB)")
    print(f"  caption:  {caption!r}" + ("" if caption else "  (empty)"))
    try:
        print(f"  account:  @{check_account(token, user_id)} (IG_USER_ID {user_id})")
    except GraphError as e:
        print(f"  account:  could not verify token: {e}")
    print(f"  host:     " + (f"https://raw.githubusercontent.com/{owner}/{REPO_NAME}/<commit>/posters/{os.path.basename(jpeg)}"
                             if owner else "gh CLI missing or not logged in (run: gh auth login)"))
    for p in problems:
        print(f"  PROBLEM:  {p}")

    if not args.live:
        print("\nWould: upload JPEG to GitHub -> POST /{IG_USER_ID}/media (image_url, caption) "
              "-> POST /{IG_USER_ID}/media_publish (creation_id)")
        print("Nothing uploaded or posted. Re-run with --live to publish.")
        return
    if problems:
        sys.exit("Refusing to post: fix the problems above first.")
    if not owner:
        sys.exit("gh CLI is required for --live (install it, then run: gh auth login)")

    repo = ensure_repo(owner)
    image_url = upload_jpeg(repo, jpeg)
    print(f"Hosted at {image_url}")
    wait_public(image_url)
    media_id, permalink = publish(token, user_id, image_url, caption)
    append_log({
        "source": src, "sha256": digest, "image_url": image_url, "caption": caption,
        "media_id": media_id, "permalink": permalink,
        "posted_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    print(f"Published media {media_id}: {permalink}")
    if entry:
        entry.update(status="posted", media_id=media_id, permalink=permalink,
                     posted_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        save_queue(queue)
        print(f"Marked queue entry {entry['name']!r} as posted")


if __name__ == "__main__":
    try:
        main()
    except (GraphError, RuntimeError, subprocess.CalledProcessError) as e:
        sys.exit(f"Error: {redact(e)}")
