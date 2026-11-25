import base64

from odoo.tools import file_open


def _fill_template(template, env):
    from .models.rental_agreement import AGREEMENT_FIELD_TOKENS
    if not template.master_pdf:
        with file_open(
            'car_rental_management_odoo/data/city_delights_contract.pdf', 'rb'
        ) as source:
            template.master_pdf = base64.b64encode(source.read())
    if not template.master_filename:
        template.master_filename = 'City Delights Contract.pdf'
    if not template.field_ids:
        fields = env['rental.agreement.template.field'].sudo()
        for sequence, (key, label, section) in enumerate(AGREEMENT_FIELD_TOKENS):
            fields.create({
                'template_id': template.id,
                'sequence': sequence * 10,
                'key': key,
                'label': label,
                'section': section,
                'required': key in ('renter_name', 'identity_number', 'vehicle_registration',
                                    'delivery_date', 'lease_period', 'delivery_place',
                                    'security_deposit', 'daily_rental'),
            })
    if template.state != 'active':
        template.action_activate()


def _seed_default_template(env):
    """Create (or repair) the City Delights master template per company."""
    Template = env['rental.agreement.template'].sudo()
    for company in env['res.company'].search([]):
        template = Template.search([
            ('company_id', '=', company.id)], limit=1)
        if not template:
            template = Template.create({
                'name': 'City Delights Standard Rental Agreement',
                'company_id': company.id,
                'version': 'City Delights supplied contract - October 2026',
                'state': 'draft',
                'is_default': True,
            })
        _fill_template(template, env)


def _get_or_create_account(env, company, code, name, account_type):
    Account = env['account.account'].sudo()
    account = Account.search([
        ('company_ids', 'in', company.id), ('code', '=', code)], limit=1)
    if not account:
        account = Account.create({
            'name': name, 'code': code, 'account_type': account_type,
            'company_ids': [(6, 0, [company.id])],
            'reconcile': account_type in ('asset_receivable', 'liability_payable'),
        })
    return account


def _get_or_create_journal(env, company, code, name, journal_type, account):
    Journal = env['account.journal'].sudo()
    journal = Journal.search([
        ('company_id', '=', company.id), ('type', '=', journal_type),
        ('code', '=', code)], limit=1)
    if not journal:
        journal = Journal.create({
            'name': name, 'code': code, 'type': journal_type,
            'company_id': company.id, 'default_account_id': account.id,
        })
    return journal


def configure_company_accounting(company):
    """Configure rental accounts/journals for one company when missing."""
    company = company.sudo()
    env = company.env
    income = _get_or_create_account(env, company, 'CRINC', 'Car Rental Income', 'income')
    damage = _get_or_create_account(env, company, 'CRDMG', 'Car Rental Damage Recovery', 'income_other')
    deposit = _get_or_create_account(env, company, 'CRDEP', 'Customer Deposit Liability', 'liability_current')
    pending = _get_or_create_account(env, company, 'CRPCG', 'Unpaid Deposit Clearing', 'liability_current')
    expense = _get_or_create_account(env, company, 'CREXP', 'Vehicle Maintenance Expense', 'expense')
    bank_account = _get_or_create_account(env, company, 'CRBNK', 'Car Rental Bank', 'asset_cash')
    bank = _get_or_create_journal(env, company, 'CRBK', 'Rental Bank', 'bank', bank_account)
    sales = _get_or_create_journal(env, company, 'CRSL', 'Rental Sales', 'sale', income)
    for line in bank.inbound_payment_method_line_ids:
        if not line.payment_account_id:
            line.payment_account_id = bank_account

    values = {}
    for field, account in (
        ('cr_income_account_id', income), ('cr_damage_account_id', damage),
        ('cr_deposit_account_id', deposit), ('cr_deposit_pending_account_id', pending),
        ('cr_expense_account_id', expense),
    ):
        if not company[field]:
            values[field] = account.id
    if not company.cr_cash_journal_id:
        values['cr_cash_journal_id'] = bank.id
    if not company.cr_sales_journal_id:
        values['cr_sales_journal_id'] = sales.id
    # Ensure the rental service products exist and have sensible prices.
    env['res.company']._ensure_default_rental_products()
    for field, external_id, price in (
        ('cr_rental_product_id', 'rental_service_product', 0),
        ('cr_deposit_product_id', 'rental_deposit_product', 0),
        ('cr_delivery_product_id', 'rental_delivery_product', 150),
        ('cr_collection_product_id', 'rental_collection_product', 200),
        ('cr_cleaning_product_id', 'rental_cleaning_product', 250),
        ('cr_late_product_id', 'rental_late_product', 400),
    ):
        product = company[field] or env.ref(
            'car_rental_management_odoo.%s' % external_id, raise_if_not_found=False)
        if product:
            if not company[field]:
                values[field] = product.id
            if external_id != 'rental_service_product' and not product.list_price:
                product.with_company(company).list_price = price
            if external_id == 'rental_deposit_product':
                product.with_company(company).taxes_id = [(5, 0, 0)]
    if values:
        company.write(values)

def _ensure_rental_accounting(env):
    """Configure rental accounts for every company."""
    for company in env['res.company'].search([]):
        configure_company_accounting(company)

def post_init_hook(env):
    service_types = env['fleet.service.type'].sudo()
    for name in ('Insurance', 'Road Licence', 'Fitness Certificate'):
        if not service_types.search([('category', '=', 'contract'), ('name', '=', name)], limit=1):
            service_types.create({'name': name, 'category': 'contract'})
    _seed_default_template(env)
    _ensure_rental_accounting(env)
    # Commit so the accounts survive the install transaction.
    env.cr.commit()
