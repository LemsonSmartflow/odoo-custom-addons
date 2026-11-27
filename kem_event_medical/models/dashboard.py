"""Management dashboard with live counts from the connected applications."""
from odoo import api, fields, models


class KemDashboard(models.TransientModel):
    _name = 'kem.dashboard'
    _description = 'Event Medical Management Dashboard'

    bookings_total = fields.Integer('Total Bookings', compute='_compute_values')
    confirmed_bookings = fields.Integer('Confirmed Bookings', compute='_compute_values')
    completed_bookings = fields.Integer('Completed Events', compute='_compute_values')
    upcoming_deployments = fields.Integer('Upcoming Deployments', compute='_compute_values')
    open_jobs = fields.Integer('Open Operational Jobs', compute='_compute_values')
    vehicles_available = fields.Integer('Available Vehicles', compute='_compute_values')
    vehicles_maintenance = fields.Integer('Vehicles in Maintenance', compute='_compute_values')
    stock_alerts = fields.Integer('Low Stock Alerts', compute='_compute_values')
    invoices_open = fields.Integer('Open Customer Invoices', compute='_compute_values')
    revenue_invoiced = fields.Monetary('Total Invoiced', compute='_compute_values')
    expenses_total = fields.Monetary('Recorded Expenses', compute='_compute_values')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('company_id')
    def _compute_values(self):
        Booking = self.env['kem.event.booking']
        Job = self.env['kem.operational.job']
        Vehicle = self.env['fleet.vehicle']
        Move = self.env['account.move']
        Expense = self.env['hr.expense']
        for dash in self:
            dash.bookings_total = Booking.search_count([])
            dash.confirmed_bookings = Booking.search_count([('state', '=', 'confirmed')])
            dash.completed_bookings = Booking.search_count([('state', '=', 'completed')])
            dash.upcoming_deployments = Booking.search_count([
                ('state', 'in', ('confirmed', 'planning', 'ready', 'in_progress'))
            ])
            dash.open_jobs = Job.search_count([('state', 'not in', ('completed', 'cancelled'))])
            dash.vehicles_available = Vehicle.search_count([('status_id.name', '=', 'Available')]) \
                if 'status_id' in Vehicle._fields else Vehicle.search_count([])
            dash.vehicles_maintenance = Vehicle.search_count([('status_id.name', '=', 'Maintenance')]) \
                if 'status_id' in Vehicle._fields else 0
            dash.stock_alerts = sum(
                1 for quant in self.env['stock.quant'].search([])
                if quant.product_id.qty_available <= (quant.product_id.reordering_min_qty or 0)
            )
            open_invoices = Move.search([('move_type', '=', 'out_invoice'), ('state', 'in', ('draft', 'posted'))])
            dash.invoices_open = len(open_invoices.filtered(lambda m: m.amount_residual > 0))
            dash.revenue_invoiced = sum(open_invoices.mapped('amount_total'))
            dash.expenses_total = sum(Expense.search([('state', 'in', ('posted', 'done'))]).mapped('total_amount'))
