#!/bin/sh
set -eu

SOURCE_URL="https://github.com/MobeenFatimaa/Insurance-Claim-Fraud-Detection-Dataset-Generator.git"
SOURCE_COMMIT="2551a1c77275464906f65daabcd6d208b7d33c32"
DESTINATION="${1:-data/source/insurance-claim-generator}"

if [ -e "$DESTINATION" ]; then
  printf '%s\n' "Destination already exists: $DESTINATION" >&2
  exit 1
fi

git clone "$SOURCE_URL" "$DESTINATION"
git -C "$DESTINATION" checkout --detach "$SOURCE_COMMIT"
ACTUAL_COMMIT=$(git -C "$DESTINATION" rev-parse HEAD)
if [ "$ACTUAL_COMMIT" != "$SOURCE_COMMIT" ]; then
  printf '%s\n' "Commit verification failed" >&2
  exit 1
fi
printf '%s\n' "Pinned dataset source ready at $DESTINATION ($ACTUAL_COMMIT)"
