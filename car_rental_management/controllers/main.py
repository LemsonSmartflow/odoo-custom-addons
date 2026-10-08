# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request


class VehicleWebsite(http.Controller):

    @http.route('/vehicles', type='http', auth='public', website=True, sitemap=True)
    def vehicle_catalog(self, **kwargs):
        """Public vehicle catalog page."""
        domain = [('website_published', '=', True)]

        # Filter by category
        category_id = kwargs.get('category')
        if category_id:
            domain.append(('rental_category_id', '=', int(category_id)))

        # Filter by destination
        destination_id = kwargs.get('destination')
        if destination_id:
            domain.append(('website_price_ids.destination_id', '=', int(destination_id)))

        vehicles = request.env['fleet.vehicle'].sudo().search(domain)

        # Get filter options
        categories = request.env['car.rental.vehicle.category'].sudo().search([])
        destinations = request.env['car.rental.destination'].sudo().search([])

        values = {
            'vehicles': vehicles,
            'categories': categories,
            'destinations': destinations,
            'selected_category': int(category_id) if category_id else False,
            'selected_destination': int(destination_id) if destination_id else False,
        }
        return request.render('car_rental_management.website_vehicle_catalog', values)

    @http.route('/vehicles/<string:slug>', type='http', auth='public', website=True, sitemap=True)
    def vehicle_detail(self, slug, **kwargs):
        """Vehicle detail page with gallery and pricing."""
        # Extract ID from slug (format: name-id)
        try:
            vehicle_id = int(slug.split('-')[-1])
        except (ValueError, IndexError):
            return request.not_found()

        vehicle = request.env['fleet.vehicle'].sudo().search([
            ('id', '=', vehicle_id),
            ('website_published', '=', True),
        ], limit=1)

        if not vehicle:
            return request.not_found()

        # Get pricing for this vehicle
        prices = vehicle.website_price_ids.sorted(key=lambda p: (p.destination_id.name, p.min_days))

        # Get gallery images
        images = vehicle.image_gallery_ids.sorted(key=lambda s: s.sequence)

        # Get related vehicles (same category)
        related_vehicles = request.env['fleet.vehicle'].sudo().search([
            ('website_published', '=', True),
            ('rental_category_id', '=', vehicle.rental_category_id.id),
            ('id', '!=', vehicle.id),
        ], limit=3)

        values = {
            'vehicle': vehicle,
            'prices': prices,
            'images': images,
            'related_vehicles': related_vehicles,
        }
        return request.render('car_rental_management.website_vehicle_detail', values)

    @http.route('/vehicles/<int:vehicle_id>/book', type='http', auth='public', website=True)
    def vehicle_booking_form(self, vehicle_id, **kwargs):
        """Booking request form."""
        vehicle = request.env['fleet.vehicle'].sudo().search([
            ('id', '=', vehicle_id),
            ('website_published', '=', True),
        ], limit=1)

        if not vehicle:
            return request.not_found()

        destinations = request.env['car.rental.destination'].sudo().search([])

        values = {
            'vehicle': vehicle,
            'destinations': destinations,
        }
        return request.render('car_rental_management.website_booking_form', values)

    @http.route('/vehicles/booking/submit', type='http', auth='public', methods=['POST'], website=True)
    def vehicle_booking_submit(self, **kwargs):
        """Process booking request and create rental order."""
        vehicle_id = int(kwargs.get('vehicle_id', 0))
        vehicle = request.env['fleet.vehicle'].sudo().browse(vehicle_id)

        if not vehicle.exists() or not vehicle.website_published:
            return request.not_found()

        # Get or create partner
        partner_email = kwargs.get('email', '').strip()
        partner_name = kwargs.get('name', '').strip()
        partner_phone = kwargs.get('phone', '').strip()

        if not partner_email or not partner_name:
            return request.redirect('/vehicles/%s?error=missing_info' % vehicle.slug)

        partner = request.env['res.partner'].sudo().search([('email', '=', partner_email)], limit=1)
        if not partner:
            partner = request.env['res.partner'].sudo().create({
                'name': partner_name,
                'email': partner_email,
                'phone': partner_phone,
            })

        # Parse dates
        pickup_date = kwargs.get('pickup_date')
        return_date = kwargs.get('return_date')
        destination_id = int(kwargs.get('destination_id', 0))

        if not pickup_date or not return_date or not destination_id:
            return request.redirect('/vehicles/%s?error=missing_dates' % vehicle.slug)

        # Create rental order
        order_vals = {
            'partner_id': partner.id,
            'rental_destination_id': destination_id,
            'rental_vehicle_category_id': vehicle.rental_category_id.id if vehicle.rental_category_id else False,
            'note': 'Online booking request via website',
        }
        order = request.env['sale.order'].sudo().create(order_vals)

        return request.render('car_rental_management.website_booking_confirmation', {
            'order': order,
            'vehicle': vehicle,
        })


class VehiclePortal(http.Controller):

    @http.route('/my/rentals', type='http', auth='user', website=True)
    def portal_rentals(self, **kwargs):
        """Customer portal - my rental orders."""
        orders = request.env['sale.order'].search([
            ('partner_id', '=', request.env.user.partner_id.id),
        ])

        values = {
            'orders': orders,
        }
        return request.render('car_rental_management.portal_my_rentals', values)

    @http.route('/my/rentals/<int:order_id>', type='http', auth='user', website=True)
    def portal_rental_detail(self, order_id, **kwargs):
        """Customer portal - rental order detail."""
        order = request.env['sale.order'].browse(order_id)

        # Ensure user can only see their own orders
        if order.partner_id != request.env.user.partner_id:
            return request.redirect('/my/rentals')

        values = {
            'order': order,
        }
        return request.render('car_rental_management.portal_rental_detail', values)
