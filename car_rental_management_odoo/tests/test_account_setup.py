"""Rental accounting configures itself and stays idempotent."""

from odoo.tests import tagged, TransactionCase

CONFIG_FIELDS = (
    'cr_income_account_id', 'cr_damage_account_id',
    'cr_deposit_account_id', 'cr_deposit_pending_account_id',
    'cr_expense_account_id', 'cr_cash_journal_id', 'cr_sales_journal_id',
)


@tagged('post_install', '-at_install')
class TestAccountSetup(TransactionCase):

    def test_ensure_rental_accounting_repairs_missing_configuration(self):
        company = self.env.company
        company.write({field: False for field in CONFIG_FIELDS})
        company.ensure_rental_accounting()
        for field in CONFIG_FIELDS:
            self.assertTrue(company[field], '%s should be configured' % field)
        self.assertEqual(company.cr_income_account_id.code, 'CRINC')
        self.assertEqual(company.cr_cash_journal_id.code, 'CRBK')
        self.assertEqual(company.cr_sales_journal_id.code, 'CRSL')

    def test_ensure_rental_accounting_is_idempotent(self):
        company = self.env.company
        company.ensure_rental_accounting()
        income = company.cr_income_account_id
        journal = company.cr_cash_journal_id
        company.ensure_rental_accounting()
        self.assertEqual(company.cr_income_account_id, income)
        self.assertEqual(company.cr_cash_journal_id, journal)
