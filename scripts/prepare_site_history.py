"""Split an unpublished Site snapshot into bounded upload commits, preserving it."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "website"


def main():
    def git(*args, env=None, data=None):
        return subprocess.run(["git", *args], cwd=SITE, env=env, input=data, check=True,
                              capture_output=True).stdout.decode().strip()

    assert not git("status", "--porcelain"), "Save the Site snapshot before splitting"
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    rows = subprocess.run(["git", "ls-tree", "-r", "-z", "HEAD"], cwd=SITE,
                          capture_output=True, check=True).stdout.split(b"\0")
    ordinary, parts = [], []
    for row in filter(None, rows):
        metadata, name = row.split(b"\t", 1)
        mode, kind, sha = metadata.decode().split()
        entry = (mode, sha, name.decode())
        (parts if entry[2].startswith("dist/downloads/") and entry[2].endswith(".part") else ordinary).append(entry)
    index = SITE / ".git" / "bounded-upload.index"
    assert not index.exists(), "Preserve and inspect the previous temporary upload index"
    env = dict(os.environ, GIT_INDEX_FILE=str(index), GIT_AUTHOR_NAME="Sites", GIT_AUTHOR_EMAIL="sites@users.noreply.openai.com",
               GIT_COMMITTER_NAME="Sites", GIT_COMMITTER_EMAIL="sites@users.noreply.openai.com")
    git("read-tree", "--empty", env=env)
    commits = []
    for batch in [ordinary] + [parts[i:i + 3] for i in range(0, len(parts), 3)]:
        for mode, sha, name in batch:
            git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{name}", env=env)
        next_tree = git("write-tree", env=env)
        parent = ["-p", commits[-1]] if commits else []
        commits.append(git("commit-tree", next_tree, *parent, env=env,
                           data=f"Prepare Site upload batch {len(commits) + 1}\n".encode()))
    assert git("rev-parse", commits[-1] + "^{tree}") == tree, "Split snapshot differs"
    backup = "refs/heads/unsplit-upload-backup"
    git("update-ref", backup, head)
    branch = git("symbolic-ref", "HEAD")
    git("update-ref", branch, commits[-1], head)
    plan = {"original_commit": head, "backup_ref": backup, "commits": commits, "tree": tree}
    (ROOT / "artifacts" / "site-upload-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Prepared {len(commits)} bounded commits; original retained at {backup}.")


if __name__ == "__main__":
    main()
