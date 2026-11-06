def migrate(cr, version):
    cr.execute("""
        ALTER TABLE res_company
        ADD COLUMN IF NOT EXISTS cr_deposit_pending_account_id integer
    """)
