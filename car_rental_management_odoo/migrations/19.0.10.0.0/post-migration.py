"""Seed rental compliance contract types and initialize service mileage targets."""


def migrate(cr, version):
    cr.execute(
        """
        INSERT INTO fleet_service_type
               (name, category, create_uid, write_uid, create_date, write_date)
        SELECT jsonb_build_object('en_US', service_type.name), 'contract', 1, 1, NOW(), NOW()
          FROM (VALUES ('Insurance'), ('Road Licence'), ('Fitness Certificate')) AS service_type(name)
         WHERE NOT EXISTS (
               SELECT 1
                 FROM fleet_service_type existing
                WHERE existing.category = 'contract'
                  AND existing.name ->> 'en_US' = service_type.name
         )
        """
    )
    cr.execute(
        """
        UPDATE fleet_vehicle vehicle
           SET rental_next_service_mileage =
                   COALESCE((
                       SELECT odometer.value
                         FROM fleet_vehicle_odometer odometer
                        WHERE odometer.vehicle_id = vehicle.id
                        ORDER BY odometer.date DESC, odometer.id DESC
                        LIMIT 1
                   ), 0) + COALESCE(vehicle.rental_service_interval, 10000)
         WHERE COALESCE(vehicle.rental_next_service_mileage, 0) <= 0
           AND COALESCE(vehicle.rental_service_interval, 0) > 0
        """
    )
