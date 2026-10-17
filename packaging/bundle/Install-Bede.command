#!/usr/bin/env bash
# School-facing entry point. Engineering verification uses a synthetic runtime.
cd "$(dirname "$0")" || exit 1
echo "Bede School Installer"
echo "====================="
echo "1) Engineering verification (simulated runtime; no Bede registry access)"
echo "2) Install actual Bede (requires access to release images)"
echo "3) Exit"
read -r -p "Select 1, 2 or 3: " choice
case "$choice" in
  1)
    echo "SIMULATION ONLY — no actual Bede services or student data."
    bash simulation/Run-Bede-Installer-Test.command
    status=$?
    ;;
  2)
    ./start.sh
    status=$?
    ;;
  3) exit 0 ;;
  *) echo "Invalid selection."; status=2 ;;
esac
echo
if [[ "$status" -ne 0 ]]; then echo "Bede setup was not completed. See the message above."; fi
read -r -p "Press Return to close... " _
exit "$status"
