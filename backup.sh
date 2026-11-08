#!/bin/sh
# Kopia zapasowa bazy aplikacji: codziennie o BACKUP_HOUR (czas lokalny wg TZ) oraz na żądanie z panelu.
# Kopie trafiają do ./backups na serwerze, starsze niż BACKUP_KEEP_DAYS dni są usuwane.
set -u
KEEP="${BACKUP_KEEP_DAYS:-14}"
HOUR="${BACKUP_HOUR:-3}"
# Domyślnie kopia NIE zawiera historii pomiarów (największe tabele: wykresy), ale zawiera logi, dziennik zmian, użytkowników, routery i listy IP.
# BACKUP_INCLUDE_METRICS=1 dołącza też historię wykresów (kopie są wtedy wielokrotnie większe).
INCL="${BACKUP_INCLUDE_METRICS:-0}"
EXCL="--exclude-table-data=iface_metrics --exclude-table-data=metrics --exclude-table-data=client_stats"
[ "$INCL" = "1" ] && EXCL=""
DIR=/backups
mkdir -p "$DIR"

do_backup() {
  f="$DIR/monitor-$(date +%Y-%m-%d_%H%M%S).dump"
  if pg_dump -h db -U monitor -d monitor -Fc $EXCL -f "$f.part"; then
    mv "$f.part" "$f"
    rm -f "$DIR/.last_error"
    echo "$(date '+%F %T') kopia OK: $(basename "$f") ($(du -h "$f" | cut -f1))"
  else
    rm -f "$f.part"
    date '+%F %T' > "$DIR/.last_error"
    echo "$(date '+%F %T') BLAD: kopia nie powiodla sie" >&2
    return 1
  fi
  find "$DIR" -maxdepth 1 -name 'monitor-*.dump' -mtime +"$KEEP" -delete
  find "$DIR" -maxdepth 1 -name '.done-*' -mtime +3 -delete
}

echo "backup: codziennie o ${HOUR}:00 (${TZ:-UTC}), przechowywanie ${KEEP} dni, historia pomiarów w kopii: $([ "$INCL" = "1" ] && echo tak || echo nie)"
sleep 15
# pierwsza kopia od razu, jeśli w katalogu nie ma żadnej
ls "$DIR"/monitor-*.dump >/dev/null 2>&1 || do_backup

while true; do
  today=$(date +%Y-%m-%d)
  if [ -f "$DIR/.now" ]; then
    rm -f "$DIR/.now"
    do_backup
  elif [ "$(date +%H)" -eq "$HOUR" ] && [ ! -f "$DIR/.done-$today" ]; then
    do_backup && touch "$DIR/.done-$today"
  fi
  sleep 20
done
