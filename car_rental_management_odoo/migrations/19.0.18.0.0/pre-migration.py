def migrate(cr, version):
    cr.execute("SELECT to_regclass('public.car_rental_journey')")
    if not cr.fetchone()[0]:
        return

    cr.execute("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'car_rental_journey'
    """)
    columns = {row[0] for row in cr.fetchall()}
    new_columns = {
        'booking_partner_id': 'integer',
        'booking_destination_id': 'integer',
        'booking_category_id': 'integer',
        'booking_vehicle_id': 'integer',
        'booking_pickup_datetime': 'timestamp without time zone',
        'booking_number_of_days': 'integer',
    }
    for column, sql_type in new_columns.items():
        if column not in columns:
            cr.execute('ALTER TABLE car_rental_journey ADD COLUMN %s %s' % (column, sql_type))

    pairs = {
        'partner_id': 'booking_partner_id',
        'destination_id': 'booking_destination_id',
        'category_id': 'booking_category_id',
        'vehicle_id': 'booking_vehicle_id',
        'pickup_datetime': 'booking_pickup_datetime',
        'number_of_days': 'booking_number_of_days',
    }
    for source, target in pairs.items():
        if source in columns:
            cr.execute(
                'UPDATE car_rental_journey SET %s = %s WHERE %s IS NULL' % (
                    target, source, target))
