# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _demo_configure_company(self):
        """Demo-only: brand the company and activate BWP when no journal items exist yet.

        Other modules' demo data may already have created journal entries in the
        default currency, in which case the currency change is skipped (Odoo blocks
        currency changes once journal items exist).
        """
        for company in self:
            if self.env['account.move.line'].sudo().search_count([('company_id', '=', company.id)]):
                continue
            company.name = 'City Delights (Pty) Ltd'
            bwp = self.env.ref('base.BWP', raise_if_not_found=False)
            if bwp and bwp != company.currency_id:
                bwp.active = True
                company.currency_id = bwp

    rental_deposit_liability_account_id = fields.Many2one(
        'account.account', string='Customer Rental Deposits Account',
        domain="[('account_type', '=', 'liability_current')]",
        help='Refundable security deposits are liabilities, not rental revenue.')
    rental_recovery_income_account_id = fields.Many2one(
        'account.account', string='Damage/Recovery Income Account',
        domain="[('account_type', '=', 'income')]",
        help='Income account for approved damage, cleaning, fuel and late recovery charges.')
    rental_deposit_journal_id = fields.Many2one(
        'account.journal', string='Deposit Bank/Cash Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        help='Journal used to post deposit receipts, applications and refunds.')
    rental_late_grace_hours = fields.Float(
        string='Late Return Grace (hours)', default=2.0,
        help='Grace period before late-return charges apply.')
    rental_late_extra_day_threshold = fields.Float(
        string='Late Return Extra-Day Threshold (hours)', default=24.0,
        help='Beyond this many late hours, the late charge switches to full rental days.')
    rental_late_hourly_rate = fields.Monetary(
        string='Late Return Hourly Rate', currency_field='currency_id',
        help='Leave 0 to default to one twenty-fourth of the applicable daily rate.')
    rental_compliance_block = fields.Boolean(
        string='Block Handover on Expired Compliance', default=False,
        help='If enabled, expired insurance / licence / fitness blocks handover; otherwise a warning is logged.')
    rental_tracker_block = fields.Boolean(
        string='Block Handover on Non-Working Tracker', default=False,
        help='If enabled, a non-operational tracker blocks handover; otherwise a warning is logged.')
