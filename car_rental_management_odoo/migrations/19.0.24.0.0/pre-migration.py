"""Version-independent re-run of the company column repair.

Odoo only executes a migration folder when an upgrade crosses that version.  A
database that was already at 19.0.23.0.0 with a missing column would therefore
never be repaired by later upgrades.  This folder re-applies the same idempotent
repair for every database upgraded to 19.0.24.0.0 or later.
"""
from odoo.tools.sql import column_exists, table_exists


COMPANY_COLUMNS = (
    'cr_deposit_pending_account_id',
    'cr_rental_product_id',
    'cr_deposit_product_id',
    'cr_delivery_product_id',
    'cr_collection_product_id',
    'cr_cleaning_product_id',
    'cr_late_product_id',
)


def migrate(cr, version):
    for field in COMPANY_COLUMNS:
        if not column_exists(cr, 'res_company', field):
            cr.execute(
                'ALTER TABLE res_company ADD COLUMN %s integer' % field
            )

    # rental_image became a related alias of image_1920.  Preserve photos that
    # were only ever uploaded through the rental UI before the ORM changes the
    # column definition.
    if table_exists(cr, 'fleet_vehicle') and column_exists(cr, 'fleet_vehicle', 'rental_image'):
        cr.execute("""
            UPDATE fleet_vehicle
               SET image_1920 = rental_image
             WHERE rental_image IS NOT NULL
               AND (image_1920 IS NULL OR image_1920 = '')
        """)
