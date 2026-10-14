#!/usr/bin/env bash
# Double-click from Finder after extracting the official Bede installer archive.
cd "$(dirname "$0")" || exit 1
./start.sh
status=$?
echo
if [[ $status -ne 0 ]]; then echo "Bede setup was not completed. See the message above."; fi
read -r -p "Press Return to close... " _
exit "$status"
