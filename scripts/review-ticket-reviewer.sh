#!/usr/bin/env sh
# review-ticket headless reviewer adapter (Unix entry; same flags as review_ticket_reviewer.py)
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python "$HERE/review_ticket_reviewer.py" "$@"
