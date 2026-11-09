#!/usr/bin/env bash
# usage: publish-event.sh <EventName> <tenant> <version>
set -euo pipefail
EVENT="$1"; TENANT="$2"; VERSION="$3"
MSG="{\"event\":\"$EVENT\",\"tenant\":\"$TENANT\",\"version\":\"$VERSION\",\"source\":\"ci\",\"ts\":\"$(date -u +%FT%TZ)\"}"
echo "$MSG" | docker exec -i kafka /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic website-events
echo "published: $MSG"
