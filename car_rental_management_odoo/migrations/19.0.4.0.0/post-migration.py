"""Retired legacy cleanup.

The original script used ``car.rental.vehicle`` / ``car.rental.customer``, which
were removed in 19.0.8.0.0 when the module moved to shared Contacts/Fleet records.
Running it on a current registry raises ``KeyError`` and aborts the upgrade, so it
is intentionally a no-op.  Legacy data conversion is handled by the 19.0.8.0.0
scripts, which operate directly on the legacy SQL tables when they are present.
"""


def migrate(cr, version):
    return
