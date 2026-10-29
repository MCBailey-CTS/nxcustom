#!/usr/bin/env bash
# Double-click to download (or update) the nxcustom project from GitHub.
#
# The first run clones it into an "nxcustom" folder next to this script (on GitHub's default branch); later runs
# pull the latest changes for whatever branch that folder has checked out. Needs Git for Windows (which also makes
# .sh files open in Git Bash on double-click).

REPO_URL="https://github.com/MCBailey-CTS/nxcustom.git"

# Keep the window open at the end so the user can read the result.
finish() {
    echo
    read -r -p "Press Enter to close..."
    exit "$1"
}

if ! command -v git >/dev/null 2>&1; then
    echo "Git is not installed. Install Git for Windows from https://git-scm.com/download/win and try again."
    finish 1
fi

TARGET="$(cd "$(dirname "$0")" && pwd)/nxcustom"

if [ -d "$TARGET/.git" ]; then
    cd "$TARGET" || finish 1
    BRANCH="$(git branch --show-current)"
    if [ -z "$BRANCH" ]; then
        echo "$TARGET is not on a branch, so there is nothing to pull. Check out a branch, then run this again."
        finish 1
    fi
    echo "Updating $TARGET (branch $BRANCH) ..."
    if ! git fetch origin "$BRANCH"; then
        echo "Could not reach GitHub - check your network connection and GitHub sign-in."
        finish 1
    fi
    if ! git pull --ff-only origin "$BRANCH"; then
        echo
        echo "The update stopped because files in $TARGET were changed locally."
        echo "Ask the NX customization team before discarding them."
        finish 1
    fi
elif [ -e "$TARGET" ]; then
    echo "$TARGET already exists but is not a git copy of the project."
    echo "Move or rename it, then run this again."
    finish 1
else
    echo "Downloading nxcustom into $TARGET ..."
    if ! git clone "$REPO_URL" "$TARGET"; then
        echo "The download failed - check your network connection and GitHub sign-in."
        finish 1
    fi
fi

echo
echo "Done. nxcustom is up to date in $TARGET on branch $(git -C "$TARGET" branch --show-current) ($(git -C "$TARGET" log -1 --format='%h %s'))."
finish 0
