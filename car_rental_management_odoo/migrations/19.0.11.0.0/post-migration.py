def migrate(cr, version):
    cr.execute("""
        UPDATE fleet_vehicle
           SET rental_category_id = category_id
         WHERE rental_category_id IS DISTINCT FROM category_id
    """)
