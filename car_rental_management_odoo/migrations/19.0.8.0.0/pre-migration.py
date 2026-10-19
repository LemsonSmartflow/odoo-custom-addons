"""19.0.8.0.0 pre-migration: reshape legacy columns before registry load.

car.rental.customer  -> res.partner
car.rental.vehicle   -> fleet.vehicle
car.rental.category  -> fleet.vehicle.model.category

Raw SQL only: the new registry has already dropped the old models.
Every step is guarded so a fresh install (no legacy tables) is a no-op.
"""


def _exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return cr.fetchone()[0] is not None


def _has_column(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return bool(cr.fetchone())


def _drop_fks_on_column(cr, table, column):
    """Drop any FK constraint still referencing the given column.

    After a column rename the old FK still points at the retired
    car.rental.* table, which rejects the new res.partner / fleet ids.
    """
    cr.execute(
        """
        SELECT c.conname
          FROM pg_constraint c
          JOIN pg_attribute a
            ON a.attrelid = c.conrelid
           AND a.attnum = ANY (c.conkey)
          JOIN pg_class t ON t.oid = c.conrelid
         WHERE t.relname = %s
           AND a.attname = %s
           AND c.contype = 'f'
        """,
        (table, column),
    )
    for (conname,) in cr.fetchall():
        cr.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{conname}"')


def migrate(cr, version):
    if not version:
        return

    # 0. Wipe all module views so stale arch (customer_id xpaths, removed
    #    views) cannot block validation. The XML files recreate them fresh.
    cr.execute(
        """
        DELETE FROM ir_ui_view v
         USING ir_model_data d
         WHERE d.model = 'ir.ui.view'
           AND d.module = 'car_rental_management_odoo'
           AND d.res_id = v.id
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'car_rental_management_odoo'
           AND model = 'ir.ui.view'
        """
    )

    # 0b. Remove stale actions bound to the retired models.
    for retired in ("car.rental.customer", "car.rental.vehicle", "car.rental.category"):
        cr.execute(
            """
            DELETE FROM ir_model_data
             WHERE module = 'car_rental_management_odoo'
               AND model = 'ir.actions.act_window'
               AND res_id IN (
                   SELECT id FROM ir_act_window WHERE res_model = %s
               )
            """,
            (retired,),
        )
        cr.execute("DELETE FROM ir_act_window WHERE res_model = %s", (retired,))

    # 1. Re-point the noupdate cron at fleet.vehicle (model dropped).
    #    Odoo 19 stores the cron's model on the linked server action
    #    (ir_act_server.model_id), not on ir_cron itself.
    if _exists(cr, "ir_cron") and _exists(cr, "ir_act_server"):
        cr.execute(
            """
            UPDATE ir_act_server s
               SET model_id = m.id
              FROM ir_model m, ir_cron c
             WHERE m.model = 'fleet.model_fleet_vehicle'
               AND c.ir_actions_server_id = s.id
               AND c.id = (
                   SELECT res_id FROM ir_model_data
                    WHERE module = 'car_rental_management_odoo'
                      AND name = 'cron_rental_reminders'
               )
               AND s.model_id IS DISTINCT FROM m.id
            """
        )

    # 2. Legacy categories -> fleet.vehicle.model.category (name is plain text,
    #    unique). Duplicate legacy names collapse onto one row.
    if _exists(cr, "car_rental_category"):
        cr.execute(
            """
            INSERT INTO fleet_vehicle_model_category
                   (name, sequence, create_uid, write_uid, create_date, write_date)
            SELECT DISTINCT c.name, 0, 1, 1, NOW(), NOW()
              FROM car_rental_category c
             WHERE c.name IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM fleet_vehicle_model_category f
                    WHERE f.name = c.name
               )
            """
        )

    # 3. customer_id -> partner_id column rename (value rewrite follows).
    for table in ("car_rental_reservation", "car_rental_rental", "car_rental_journey"):
        if _exists(cr, table) and _has_column(cr, table, "customer_id"):
            cr.execute(
                f'ALTER TABLE "{table}" RENAME COLUMN customer_id TO partner_id'
            )

    # 4. partner_id values: old customer ids -> res.partner ids.
    #    The FK from the rename still targets car_rental_customer, so it
    #    must be dropped before the values can point at res_partner.
    #    Unmapped rows are nulled first so a customer id can never leak
    #    through as a partner id.
    if _exists(cr, "car_rental_customer"):
        for table in ("car_rental_reservation", "car_rental_rental", "car_rental_journey"):
            if not (_exists(cr, table) and _has_column(cr, table, "partner_id")):
                continue
            _drop_fks_on_column(cr, table, "partner_id")
            # Only remap when partner_id points to a legacy car.rental.customer row
            # and that row maps to a real res.partner. Never NULL valid partner IDs.
            cr.execute(
                f"""
                UPDATE "{table}" t
                   SET partner_id = c.partner_id
                  FROM car_rental_customer c
                 WHERE t.partner_id = c.id
                   AND c.partner_id IS NOT NULL
                """
            )
            # If somehow partner_id is a legacy customer id with no partner mapping,
            # null it (data loss guard) but only if it was truly a legacy id.
            cr.execute(
                f"""
                UPDATE "{table}" t
                   SET partner_id = NULL
                 WHERE t.partner_id IN (
                       SELECT id FROM car_rental_customer WHERE partner_id IS NULL
                   )
                """
            )

    # 5. vehicle_id -> fleet.vehicle ids via legacy fleet_vehicle_id link.
    if _exists(cr, "car_rental_vehicle"):
        for table in ("car_rental_reservation", "car_rental_rental",
                      "car_rental_journey", "car_rental_check", "car_rental_damage_case"):
            if not (_exists(cr, table) and _has_column(cr, table, "vehicle_id")):
                continue
            _drop_fks_on_column(cr, table, "vehicle_id")
            cr.execute(
                f"""
                UPDATE "{table}" t
                   SET vehicle_id = NULL
                 WHERE t.vehicle_id IS NOT NULL
                   AND t.vehicle_id NOT IN (
                       SELECT id FROM car_rental_vehicle
                        WHERE fleet_vehicle_id IS NOT NULL
                   )
                """
            )
            cr.execute(
                f"""
                UPDATE "{table}" t
                   SET vehicle_id = v.fleet_vehicle_id
                  FROM car_rental_vehicle v
                 WHERE t.vehicle_id = v.id
                   AND v.fleet_vehicle_id IS NOT NULL
                """
            )

        # 5b. maintenance_request.rental_vehicle_id -> fleet.vehicle ids.
        if _exists(cr, "maintenance_request") and _has_column(cr, "maintenance_request", "rental_vehicle_id"):
            _drop_fks_on_column(cr, "maintenance_request", "rental_vehicle_id")
            cr.execute(
                """
                UPDATE maintenance_request t
                   SET rental_vehicle_id = NULL
                 WHERE t.rental_vehicle_id IS NOT NULL
                   AND t.rental_vehicle_id NOT IN (
                       SELECT id FROM car_rental_vehicle
                        WHERE fleet_vehicle_id IS NOT NULL
                   )
                """
            )
            cr.execute(
                """
                UPDATE maintenance_request t
                   SET rental_vehicle_id = v.fleet_vehicle_id
                  FROM car_rental_vehicle v
                 WHERE t.rental_vehicle_id = v.id
                   AND v.fleet_vehicle_id IS NOT NULL
                """
            )

    # 6. category_id: legacy category ids -> fleet category ids (matched by
    #    name; row was ensured in step 2).
    if _exists(cr, "car_rental_category"):
        for table in ("car_rental_reservation", "car_rental_journey", "car_rental_rate_rule"):
            if not (_exists(cr, table) and _has_column(cr, table, "category_id")):
                continue
            _drop_fks_on_column(cr, table, "category_id")
            cr.execute(
                f"""
                UPDATE "{table}" t
                   SET category_id = f.id
                  FROM car_rental_category c
                  JOIN fleet_vehicle_model_category f ON f.name = c.name
                 WHERE t.category_id = c.id
                """
            )
            cr.execute(
                f"""
                UPDATE "{table}" t
                   SET category_id = NULL
                 WHERE t.category_id IS NOT NULL
                   AND t.category_id NOT IN (SELECT id FROM fleet_vehicle_model_category)
                """
            )
