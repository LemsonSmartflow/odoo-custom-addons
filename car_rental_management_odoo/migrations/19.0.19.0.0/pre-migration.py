def migrate(cr, version):
    cr.execute("""
        SELECT data_type
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'car_rental_check'
           AND column_name = 'clean'
    """)
    column = cr.fetchone()
    if not column or column[0] == 'boolean':
        return
    cr.execute('ALTER TABLE car_rental_check ALTER COLUMN clean DROP DEFAULT')
    cr.execute("""
        ALTER TABLE car_rental_check
        ALTER COLUMN clean TYPE boolean
        USING CASE
            WHEN clean = 'yes' THEN TRUE
            WHEN clean = 'no' THEN FALSE
            ELSE FALSE
        END
    """)
