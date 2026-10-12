from datetime import timedelta

from odoo import api, fields, models

from .workflow import window


class Dashboard(models.Model):
    _inherit = 'car.rental.dashboard'

    company_id = fields.Many2one('res.company', compute='_compute_company', search='_search_company', store=False)
    currency_id = fields.Many2one(related='company_id.currency_id')
    reserved_vehicles = fields.Integer(compute='_compute_dashboard')
    maintenance_vehicles = fields.Integer(compute='_compute_dashboard')
    damaged_vehicles = fields.Integer(compute='_compute_dashboard')
    inspection_vehicles = fields.Integer(compute='_compute_dashboard')
    deposits_held = fields.Monetary(compute='_compute_dashboard')
    damage_recovery = fields.Monetary(compute='_compute_dashboard')
    maintenance_costs = fields.Monetary(compute='_compute_dashboard')
    rental_income = fields.Monetary(compute='_compute_dashboard')
    utilization = fields.Float(compute='_compute_dashboard', string='Fleet Utilisation (%)')
    period_start = fields.Date(default=lambda self: fields.Date.today().replace(day=1), required=True)
    period_end = fields.Date(default=fields.Date.today, required=True)
    vehicle_ids = fields.Many2many('car.rental.vehicle', compute='_compute_dashboard')

    @api.depends_context('company')
    def _compute_company(self):
        for dashboard in self:
            dashboard.company_id = self.env.company

    def _search_company(self, operator, value):
        company = self.env.company.id
        if operator in ('in', 'not in'):
            matches = company in value
            if operator == 'not in':
                matches = not matches
        elif operator in ('=', '!='):
            matches = company == value
            if operator == '!=':
                matches = not matches
        else:
            return [('id', '=', 0)]
        return [] if matches else [('id', '=', 0)]

    @api.depends_context('company')
    def _compute_dashboard(self):
        for dashboard in self:
            domain = [('company_id', '=', dashboard.company_id.id)]
            vehicles = self.env['car.rental.vehicle'].search(domain + [('registration_number', '!=', False), ('status', 'not in', ['setup', 'decommissioned'])])
            rentals = self.env['car.rental.rental'].search(domain)
            invoices = rentals.sudo().mapped('invoice_ids').filtered(lambda m: m.state == 'posted')
            dashboard.total_vehicles = len(vehicles)
            for field, state in [('available_vehicles', 'available'), ('rented_vehicles', 'rented'), ('reserved_vehicles', 'reserved'), ('maintenance_vehicles', 'maintenance'), ('damaged_vehicles', 'damaged')]:
                dashboard[field] = len(vehicles.filtered(lambda v: v.status == state))
            dashboard.inspection_vehicles = len(vehicles.filtered(lambda v: v.status in ('returned', 'inspection', 'cleaning')))
            dashboard.total_customers = self.env['car.rental.customer'].search_count(domain)
            dashboard.confirmed_reservations = self.env['car.rental.reservation'].search_count(domain + [('status', '=', 'confirmed'), ('rental_ids', '=', False)])
            dashboard.ongoing_rentals = len(rentals.filtered(lambda r: r.status == 'ongoing'))
            dashboard.revenue = sum(rentals.mapped('paid_total'))
            dashboard.outstanding_balance = sum(rentals.mapped('financial_balance'))
            dashboard.deposits_held = sum(rentals.mapped('deposit_held'))
            dashboard.rental_income = sum(invoices.filtered(lambda m: m.rental_invoice_kind in ('rental', 'late', 'cleaning')).mapped('amount_untaxed_signed'))
            dashboard.damage_recovery = sum(invoices.filtered(lambda m: m.rental_invoice_kind == 'damage').mapped('amount_untaxed_signed'))
            requests = self.env['maintenance.request'].sudo().search(domain + [('rental_vehicle_id', '!=', False)])
            dashboard.maintenance_costs = sum(requests.mapped('rental_cost'))
            start, end = dashboard.period_start, dashboard.period_end
            eligible = vehicles.filtered(lambda v: v.status not in ('setup', 'decommissioned'))
            days = max((end - start).days + 1, 0) if start and end else 0
            rented_days = 0
            for vehicle in eligible:
                # Count the union of rental days so duplicate historical rentals never exceed 100%.
                occupied = set()
                for rental in rentals.filtered(lambda r: r.vehicle_id == vehicle and r.actual_pickup_datetime):
                    first = max(start, rental.actual_pickup_datetime.date()) if start else None
                    last = min(end, (rental.actual_return_datetime or fields.Datetime.now()).date()) if end else None
                    if first and last and last >= first:
                        occupied.update(first + timedelta(days=n) for n in range((last - first).days + 1))
                rented_days += len(occupied)
            dashboard.utilization = rented_days / (len(eligible) * days) * 100 if eligible and days else 0
            dashboard.vehicle_ids = vehicles

    def action_refresh(self):
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_reserved(self):
        return dict(window('Reserved Vehicles', 'car.rental.vehicle', [('status', '=', 'reserved')]), view_mode='kanban,list,form')

    def action_maintenance(self):
        return window('Fleet Maintenance', 'maintenance.request', [('rental_vehicle_id', '!=', False)])

    def action_damage(self):
        return window('Damage Assessments', 'car.rental.damage.case')

    def action_deposits(self):
        return window('Security Deposit Transactions', 'car.rental.deposit.transaction')
