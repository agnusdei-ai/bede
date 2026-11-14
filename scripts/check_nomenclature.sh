#!/usr/bin/env bash
# Fails if any tracked file uses the banned nomenclature (owner rule
# 2026-11-14): the three words assembled below. Test data and stand-ins are
# called "sample", "test", "example" or "mock" instead.
#
# The words are built from pieces so this file passes its own check. The one
# exemption is the full phrase for "AI" ($c intelligence) in the two notices,
# whose SHA-256 binds every consent acknowledgement and school authorization;
# they change only through counsel (owner ruling 2026-11-14).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

a="synth""etic"; b="simul""ated"; c="artifi""cial"
pattern="${a}|${b}|${c}"
notices=(homeschool-api/data/consent_notice.txt homeschool-api/data/school_data_notice.txt)

found=$(git grep -n -I -i -E "$pattern" -- . ':(exclude).claude' \
  ":(exclude)${notices[0]}" ":(exclude)${notices[1]}" || true)
# In the notices, only "<c> intelligence" is allowed.
for f in "${notices[@]}"; do
  extra=$(grep -n -i -E "$pattern" "$f" | sed -E "s/${c} intelligence//Ig" | grep -i -E "$pattern" || true)
  [ -n "$extra" ] && found+=$'\n'"$f:$extra"
done
# File and directory names too.
names=$(git ls-files | grep -i -E "$pattern" || true)

if [ -n "${found//[$'\n']/}" ] || [ -n "$names" ]; then
  echo "Banned nomenclature found (use sample, test, example or mock):"
  [ -n "${found//[$'\n']/}" ] && echo "$found"
  [ -n "$names" ] && echo "$names"
  exit 1
fi
echo "No banned nomenclature."
