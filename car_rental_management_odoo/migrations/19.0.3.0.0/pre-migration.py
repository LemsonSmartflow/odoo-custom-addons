def migrate(cr, version):
    # Keep the prices agreed on existing reservations rather than repricing history.
    cr.execute('ALTER TABLE car_rental_reservation ADD COLUMN IF NOT EXISTS quoted_daily_rate double precision')
    cr.execute('UPDATE car_rental_reservation SET quoted_daily_rate = CASE WHEN number_of_days > 0 THEN amount / number_of_days ELSE 0 END WHERE quoted_daily_rate IS NULL')
    cr.execute('ALTER TABLE car_rental_reservation ADD COLUMN IF NOT EXISTS legacy_booking boolean')
    cr.execute('UPDATE car_rental_reservation SET legacy_booking = TRUE WHERE legacy_booking IS NULL')
    cr.execute('ALTER TABLE car_rental_payment ADD COLUMN IF NOT EXISTS ledger_state varchar')
    cr.execute("UPDATE car_rental_payment SET ledger_state = 'legacy' WHERE ledger_state IS NULL")
