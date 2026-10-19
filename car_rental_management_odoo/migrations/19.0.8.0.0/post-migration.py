"""19.0.8.0.0 post-migration: copy legacy data onto res.partner / fleet.vehicle.

Runs after the new registry is loaded. Legacy tables are read via SQL only
(car.rental.customer / car.rental.vehicle no longer exist as models).
All writes go to res_partner, fleet_vehicle, fleet_service_type,
fleet_vehicle_log_contract and the new M2M rel tables.
"""


def _exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return cr.fetchone()[0] is not None


def migrate(cr, version):
    if not version:
        return

    # ── 1. Partners: rental identity fields (COALESCE keeps real CRM data). ──
    if _exists(cr, "car_rental_customer"):
        cr.execute(
            """
            UPDATE res_partner p
               SET rental_cin              = COALESCE(p.rental_cin, c.cin),
                   rental_date_of_birth    = COALESCE(p.rental_date_of_birth, c.date_of_birth),
                   rental_driving_license  = COALESCE(p.rental_driving_license, c.driving_license),
                   rental_license_issue_date = COALESCE(p.rental_license_issue_date, c.license_issue_date),
                   rental_license_expiry   = COALESCE(p.rental_license_expiry, c.license_expiry),
                   rental_postal_address   = COALESCE(p.rental_postal_address, c.postal_address),
                   street                  = COALESCE(p.street, c.address),
                   phone                   = COALESCE(p.phone, c.phone),
                   email                   = COALESCE(p.email, c.email),
                   rental_enabled          = TRUE,
                   write_date              = NOW(),
                   write_uid               = 1
              FROM car_rental_customer c
             WHERE p.id = c.partner_id
            """
        )

        # Legacy document attachments -> partner rental_document_ids rel.
        if _exists(cr, "car_rental_customer_ir_attachment_rel"):
            cr.execute(
                """
                INSERT INTO rental_partner_document_rel
                           (res_partner_id, ir_attachment_id)
                SELECT c.partner_id, r.ir_attachment_id
                  FROM car_rental_customer_ir_attachment_rel r
                  JOIN car_rental_customer c ON c.id = r.car_rental_customer_id
                 WHERE c.partner_id IS NOT NULL
                ON CONFLICT DO NOTHING
                """
            )

    # ── 2. Fleet vehicles: rental fields via legacy fleet_vehicle_id link. ──
    if _exists(cr, "car_rental_vehicle"):
        cr.execute(
            """
            UPDATE fleet_vehicle fv
               SET rental_status = CASE v.status
                     WHEN 'rented'      THEN 'rented'
                     WHEN 'reserved'    THEN 'reserved'
                     WHEN 'returned'    THEN 'returned'
                     WHEN 'maintenance' THEN 'maintenance'
                     WHEN 'damaged'     THEN 'damaged'
                     WHEN 'inspection'  THEN 'inspection'
                     WHEN 'cleaning'    THEN 'cleaning'
                     ELSE 'available'
                   END,
                   rental_category_id = f.id,
                   rental_daily_rate  = COALESCE(v.daily_price, 0),
                   rental_tracker_working = COALESCE(v.tracker_working, TRUE),
                   rental_service_interval = COALESCE(v.service_interval, 10000),
                   rental_next_service_mileage = v.next_service_mileage,
                   rental_next_service_date = v.next_service_date,
                   write_date = NOW(),
                   write_uid  = 1
              FROM car_rental_vehicle v
              LEFT JOIN car_rental_category c ON c.id = v.category_id
              LEFT JOIN fleet_vehicle_model_category f ON f.name = c.name
             WHERE fv.id = v.fleet_vehicle_id
            """
        )

        # Vehicle document attachments -> fleet rental_document_ids rel.
        if _exists(cr, "car_rental_vehicle_ir_attachment_rel"):
            cr.execute(
                """
                INSERT INTO fleet_vehicle_rental_document_rel
                           (fleet_vehicle_id, ir_attachment_id)
                SELECT v.fleet_vehicle_id, r.ir_attachment_id
                  FROM car_rental_vehicle_ir_attachment_rel r
                  JOIN car_rental_vehicle v ON v.id = r.car_rental_vehicle_id
                 WHERE v.fleet_vehicle_id IS NOT NULL
                ON CONFLICT DO NOTHING
                """
            )

        # Odometer log from legacy mileage (only when no history exists yet).
        cr.execute(
            """
            INSERT INTO fleet_vehicle_odometer
                   (vehicle_id, value, date, create_uid, write_uid,
                    create_date, write_date)
            SELECT v.fleet_vehicle_id, v.mileage, CURRENT_DATE, 1, 1, NOW(), NOW()
              FROM car_rental_vehicle v
             WHERE v.fleet_vehicle_id IS NOT NULL
               AND COALESCE(v.mileage, 0) > 0
               AND NOT EXISTS (
                   SELECT 1 FROM fleet_vehicle_odometer o
                    WHERE o.vehicle_id = v.fleet_vehicle_id
               )
            """
        )

        # Compliance service types (JSONB translated names) + log contracts.
        cr.execute(
            """
            INSERT INTO fleet_service_type
                   (name, category, create_uid, write_uid, create_date, write_date)
            SELECT jsonb_build_object('en_US', t.n), 'contract', 1, 1, NOW(), NOW()
              FROM (VALUES ('Insurance'), ('Road Licence'), ('Fitness Certificate')) AS t(n)
             WHERE NOT EXISTS (
                   SELECT 1 FROM fleet_service_type s
                    WHERE s.category = 'contract'
                      AND s.name ->> 'en_US' = t.n
               )
            """
        )
        for legacy, subtype in (
            ("insurance", "Insurance"),
            ("road_license", "Road Licence"),
            ("fitness", "Fitness Certificate"),
        ):
            expiry_col = f"{legacy}_expiry"
            ref_col = {
                "insurance": "insurance_policy",
                "road_license": "road_license_number",
                "fitness": "fitness_number",
            }[legacy]
            cr.execute(
                f"""
                INSERT INTO fleet_vehicle_log_contract
                       (vehicle_id, cost_subtype_id, company_id, user_id,
                        name, ins_ref, state, cost_frequency, date,
                        start_date, expiration_date, amount, cost_generated,
                        active, create_uid, write_uid, create_date, write_date)
                SELECT v.fleet_vehicle_id, st.id, fv.company_id, 1,
                       %(subtype)s, v.{ref_col},
                       CASE WHEN v.{expiry_col} >= CURRENT_DATE
                            THEN 'open' ELSE 'expired' END,
                       'month', CURRENT_DATE,
                       CURRENT_DATE - INTERVAL '1 year', v.{expiry_col},
                       0, 0, TRUE, 1, 1, NOW(), NOW()
                  FROM car_rental_vehicle v
                  JOIN fleet_vehicle fv ON fv.id = v.fleet_vehicle_id
                  JOIN fleet_service_type st
                    ON st.category = 'contract'
                   AND st.name ->> 'en_US' = %(subtype)s
                 WHERE v.fleet_vehicle_id IS NOT NULL
                   AND (v.{expiry_col} IS NOT NULL OR v.{ref_col} IS NOT NULL)
                   AND NOT EXISTS (
                       SELECT 1 FROM fleet_vehicle_log_contract lc
                        WHERE lc.vehicle_id = v.fleet_vehicle_id
                          AND lc.cost_subtype_id = st.id
                   )
                """,
                {"subtype": subtype},
            )

    # ── 3. Drop the leftover reverse link column on fleet_vehicle. ──
    cr.execute("ALTER TABLE fleet_vehicle DROP COLUMN IF EXISTS rental_vehicle_id")

    # ── 4. §7.2 Retire car.rental.payment -> account.payment. ──
    _migrate_payments_to_account_payment(cr)

    # ── 5. §8.2 Locked sale.order for already-invoiced rentals without one. ──
    _create_missing_sale_orders(cr)


def _migrate_payments_to_account_payment(cr):
    """Link existing account.payments to rentals via invoice reconciliation,
    mirror remaining legacy car_rental_payment rows as draft account.payments,
    then drop the retired table."""
    if not _exists(cr, "car_rental_payment"):
        return

    from odoo import api, SUPERUSER_ID

    # 4a. Link posted account.payments to rentals through the receivable
    #     reconciliation chain (payment line <-> invoice line).
    cr.execute(
        """
        UPDATE account_payment p
           SET car_rental_id = sub.car_rental_id
          FROM (
              SELECT DISTINCT ON (p2.id) p2.id AS payment_id, am.car_rental_id
                FROM account_payment p2
                JOIN account_move_line paml ON paml.payment_id = p2.id
                JOIN account_partial_reconcile pr
                  ON pr.credit_move_id = paml.id OR pr.debit_move_id = paml.id
                JOIN account_move_line iaml
                  ON iaml.id = CASE WHEN pr.credit_move_id = paml.id
                                    THEN pr.debit_move_id ELSE pr.credit_move_id END
                JOIN account_move am ON am.id = iaml.move_id
               WHERE am.car_rental_id IS NOT NULL
                 AND am.move_type = 'out_invoice'
                 AND p2.car_rental_id IS NULL
               ORDER BY p2.id, am.id
          ) sub
         WHERE p.id = sub.payment_id
    """
    )

    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        "SELECT id, reference, rental_id, paid_amount, payment_date, "
        "ledger_state, account_move_id, collection_reference "
        "FROM car_rental_payment"
    )
    for reference, rental_ref, rental_id, paid_amount, payment_date, ledger_state, account_move_id, collection_reference in cr.fetchall():
        rental = env["car.rental.rental"].browse(rental_id).exists()
        if not rental:
            continue
        # Skip rows already covered by a linked account.payment of the same amount.
        if env["account.payment"].search_count(
            [("car_rental_id", "=", rental_id), ("amount", "=", paid_amount)], limit=1
        ):
            continue
        journal = rental.company_id.cr_cash_journal_id or env["account.journal"].search(
            [("type", "in", ("bank", "cash")), ("company_id", "=", rental.company_id.id)],
            limit=1,
        )
        if not journal:
            continue
        payment = env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": rental.partner_id.id,
                "amount": paid_amount,
                "date": payment_date,
                "journal_id": journal.id,
                "memo": reference,
                "car_rental_id": rental.id,
                "rental_invoice_kind": "rental",
                "collection_reference": collection_reference or False,
                "rental_legacy": ledger_state == "legacy",
            }
        )
        if ledger_state == "posted" and account_move_id:
            # Link the already-posted manual entry; do not create new accounting.
            cr.execute(
                "UPDATE account_payment SET move_id = %s, state = 'paid' WHERE id = %s",
                (account_move_id, payment.id),
            )

    cr.execute("DROP TABLE IF EXISTS car_rental_payment")


def _create_missing_sale_orders(cr):
    """§8.2: every already-invoiced rental must have a sales order under the
    new mandatory-order policy. Create a confirmed order matching the invoice."""
    from odoo import api, fields, SUPERUSER_ID

    cr.execute(
        """
        SELECT DISTINCT r.id
          FROM car_rental_rental r
          JOIN account_move am ON am.car_rental_id = r.id
         WHERE r.sale_order_id IS NULL
           AND am.move_type = 'out_invoice'
           AND am.state != 'cancel'
        """
    )
    env = api.Environment(cr, SUPERUSER_ID, {})
    for (rental_id,) in cr.fetchall():
        rental = env["car.rental.rental"].browse(rental_id).exists()
        if not rental or rental.sale_order_id:
            continue
        invoice = env["account.move"].search(
            [
                ("car_rental_id", "=", rental_id),
                ("move_type", "=", "out_invoice"),
                ("state", "!=", "cancel"),
            ],
            limit=1,
        )
        if not invoice:
            continue
        lines = [
            fields.Command.create(
                {
                    "name": line.name,
                    "product_id": line.product_id.id or False,
                    "product_uom_qty": line.quantity,
                    "price_unit": line.price_unit,
                    "tax_ids": [fields.Command.set(line.tax_ids.ids)],
                }
            )
            for line in invoice.invoice_line_ids.filtered(lambda l: not l.display_type)
        ]
        order = env["sale.order"].with_company(rental.company_id).create(
            {
                "partner_id": rental.partner_id.id,
                "company_id": rental.company_id.id,
                "currency_id": rental.currency_id.id,
                "origin": rental.reference,
                "car_rental_id": rental.id,
                "order_line": lines,
            }
        )
        order.action_confirm()
        if "locked" in order._fields:
            order.locked = True
        env.cr.execute(
            "UPDATE car_rental_rental SET sale_order_id = %s WHERE id = %s",
            (order.id, rental.id),
        )
