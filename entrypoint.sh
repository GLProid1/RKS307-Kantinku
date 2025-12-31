#!/bin/sh

# Tunggu sampai Postgres siap
if [ "$DB_ENGINE" = "django.db.backends.postgresql" ]
then
     echo "Menunggun database..."

     while ! nc -z $DB_HOST $DB_PORT; do
       sleep 0.1
     done

     echo "Database Postgresql siap!"

fi

if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "Status: LEADER. Melakukan migrasi database..."
    python manage.py migrate

else
    echo "Status: FOLLOWER. Melewati migrasi..."
fi

exec "$@"
