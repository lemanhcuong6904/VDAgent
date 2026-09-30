#!/bin/sh
# Initialise an empty data directory without touching populated databases.
# Warehouse and real-estate DW are built only when their file is absent (both seeders rebuild from scratch);
# seed_users.py is idempotent (schema + demo users). Paths come from $VDAGENT_CONFIG.
set -eu
mkdir -p var
if [ -f var/warehouse.db ]; then echo "seed: var/warehouse.db exists, kept"; else python data/seed_warehouse.py; fi
if [ -f var/re_warehouse.db ]; then echo "seed: var/re_warehouse.db exists, kept"; else python data/seed_re_warehouse.py; fi
python data/seed_users.py
