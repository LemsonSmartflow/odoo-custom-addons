"""Classify legacy rental identity numbers when matching passport evidence exists."""


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE res_partner
           SET rental_identity_type = 'omang'
         WHERE rental_identity_type IS NULL
    """)
    cr.execute("""
        UPDATE res_partner partner
           SET rental_identity_type = 'passport',
               rental_passport_number = partner.rental_cin,
               rental_cin = NULL
         WHERE partner.rental_cin IS NOT NULL
           AND EXISTS (
               SELECT 1
                 FROM rental_partner_passport_rel passport_document
                WHERE passport_document.res_partner_id = partner.id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM rental_partner_omang_rel omang_document
                WHERE omang_document.res_partner_id = partner.id
           )
    """)
