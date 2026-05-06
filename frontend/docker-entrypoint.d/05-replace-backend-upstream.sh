#!/bin/sh
set -e
# Avoid envsubst: replace placeholder so real nginx vars ($uri, $host, …) stay intact.
UP="${BACKEND_UPSTREAM:-backend:8000}"
sed -i "s|__BACKEND_UPSTREAM__|${UP}|g" /etc/nginx/conf.d/default.conf
