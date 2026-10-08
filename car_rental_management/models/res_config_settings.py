# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rental_deposit_liability_account_id = fields.Many2one(
        related='company_id.rental_deposit_liability_account_id', readonly=False, string='Customer Rental Deposits Account')
    rental_recovery_income_account_id = fields.Many2one(
        related='company_id.rental_recovery_income_account_id', readonly=False, string='Damage/Recovery Income Account')
    rental_deposit_journal_id = fields.Many2one(
        related='company_id.rental_deposit_journal_id', readonly=False, string='Deposit Bank/Cash Journal')
    rental_late_grace_hours = fields.Float(
        related='company_id.rental_late_grace_hours', readonly=False, string='Late Return Grace (hours)')
    rental_late_extra_day_threshold = fields.Float(
        related='company_id.rental_late_extra_day_threshold', readonly=False, string='Late Return Extra-Day Threshold (hours)')
    rental_late_hourly_rate = fields.Monetary(
        related='company_id.rental_late_hourly_rate', readonly=False, string='Late Return Hourly Rate')
    rental_compliance_block = fields.Boolean(
        related='company_id.rental_compliance_block', readonly=False, string='Block Handover on Expired Compliance')
    rental_tracker_block = fields.Boolean(
        related='company_id.rental_tracker_block', readonly=False, string='Block Handover on Non-Working Tracker')
