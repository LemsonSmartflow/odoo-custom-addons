def migrate(cr, version):
    cr.execute("""
        UPDATE car_rental_journey AS journey
           SET booking_delivery_service = COALESCE(reservation.delivery_service, FALSE),
               booking_delivery_address = reservation.delivery_address,
               booking_delivery_fee = COALESCE(reservation.delivery_fee, 0),
               booking_collection_service = COALESCE(reservation.collection_service, FALSE),
               booking_collection_address = reservation.collection_address,
               booking_collection_fee = COALESCE(reservation.collection_fee, 0)
          FROM car_rental_reservation AS reservation
         WHERE journey.reservation_id = reservation.id
           AND journey.step = 'booking'
    """)
