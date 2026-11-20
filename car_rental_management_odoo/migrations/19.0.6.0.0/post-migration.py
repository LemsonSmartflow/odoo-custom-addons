"""Retired first shared-record sync.

The original script imported ``models/shared_records.py`` and used the removed
``car.rental.customer`` / ``car.rental.vehicle`` models.  Both were retired in
19.0.8.0.0; importing them raises ``ModuleNotFoundError`` and aborts upgrades from
older versions.  The 19.0.8.0.0 pre/post migrations perform the equivalent data
conversion directly against the legacy SQL tables, so this script is a no-op.
"""


def migrate(cr, version):
    return
