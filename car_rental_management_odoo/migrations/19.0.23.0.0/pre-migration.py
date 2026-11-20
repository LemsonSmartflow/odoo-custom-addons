"""Repair company columns introduced with the deposit-clearing/charge-product work.

Several ``res.company`` many2one fields were added by the same development commit,
but on some upgraded databases only part of the physical columns were created
(stale ``ir_model_fields`` metadata makes the ORM skip column creation).  Adding
them here, before the registry is loaded, keeps upgrades and fresh installs equal.
"""
from odoo.tools.sql import column_exists


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
