#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "Usage: $0 PROJECT_ID REGION SERVICE MIGRATION_JOB IMAGE" >&2
  exit 2
fi

PROJECT_ID=$1
REGION=$2
SERVICE=$3
MIGRATION_JOB=$4
IMAGE=$5
CANDIDATE_TAG="candidate-$(date -u +%Y%m%d%H%M%S)"

gcloud run jobs update "$MIGRATION_JOB" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" --quiet
gcloud run jobs execute "$MIGRATION_JOB" --project "$PROJECT_ID" --region "$REGION" --wait
gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" --no-traffic --tag "$CANDIDATE_TAG" --quiet

CANDIDATE_URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format="value(status.traffic[?tag='$CANDIDATE_TAG'].url)")
if [[ -z "$CANDIDATE_URL" ]]; then
  echo "No candidate URL was returned" >&2
  exit 1
fi
curl --fail --silent --show-error --retry 3 "$CANDIDATE_URL/health" >/dev/null
curl --fail --silent --show-error --retry 3 "$CANDIDATE_URL/ready" >/dev/null
gcloud run services update-traffic "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --to-latest --quiet
