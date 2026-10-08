# Part of Odoo. See LICENSE file for full copyright and licensing details.


def post_init_hook(env):
    """Recompute stored related fields on mail templates created during install.

    Related stored Char fields (mail.template.model) can be left NULL when
    records are created via XML data during a module install, which breaks
    send_mail. Force the computation after install.
    """
    templates = env['mail.template'].search([('model_id', '!=', False), ('model', '=', False)])
    if templates:
        env.add_to_compute(templates._fields['model'], templates)
        env.flush_all()
