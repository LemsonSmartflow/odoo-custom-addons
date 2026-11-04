def post_init_hook(env):
    service_types = env['fleet.service.type'].sudo()
    for name in ('Insurance', 'Road Licence', 'Fitness Certificate'):
        if not service_types.search([('category', '=', 'contract'), ('name', '=', name)], limit=1):
            service_types.create({'name': name, 'category': 'contract'})
