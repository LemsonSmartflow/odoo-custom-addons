# Design: Vehicle Website Portal

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    PUBLIC WEBSITE                        │
│                                                         │
│  /vehicles          → Vehicle Catalog (grid/list)       │
│  /vehicles/<slug>   → Vehicle Detail (gallery, pricing) │
│  /booking/<id>      → Booking Request Form              │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                   CUSTOMER PORTAL                        │
│                                                         │
│  /my/rentals        → My Rental Orders                  │
│  /my/documents      → Uploaded documents                │
│  /my/invoices       → Invoices & payments               │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                    BACKEND (ORM)                         │
│                                                         │
│  fleet.vehicle      → Extended with website fields      │
│  sale.order         → Portal access rules               │
│  car.rental.deposit → Portal display                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Model Extensions

### fleet.vehicle (website fields)
```python
class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    # Website fields
    website_published = fields.Boolean('Published', copy=False)
    website_sequence = fields.Integer('Website Sequence')
    website_description = fields.Html('Description')
    website_price_ids = fields.One2many(
        'vehicle.website.price', 'vehicle_id', string='Website Pricing')
    slug = fields.Char('URL Slug', compute='_compute_slug')
    image_gallery_ids = fields.One2many(
        'vehicle.image.gallery', 'vehicle_id', string='Photo Gallery')
```

### vehicle.website.price (new model)
```python
class VehicleWebsitePrice(models.Model):
    _name = 'vehicle.website.price'
    _description = 'Vehicle Website Pricing Display'

    vehicle_id = fields.Many2one('fleet.vehicle')
    destination_id = fields.Many2one('car.rental.destination')
    min_days = fields.Integer()
    max_days = fields.Integer()
    daily_rate = fields.Float()
    currency_id = fields.Many2one('res.currency')
    total_price = fields.Float(compute='_compute_total')
```

### vehicle.image.gallery (new model)
```python
class VehicleImageGallery(models.Model):
    _name = 'vehicle.image.gallery'
    _description = 'Vehicle Photo Gallery'
    _order = 'sequence'

    vehicle_id = fields.Many2one('fleet.vehicle')
    image = fields.Image('Photo', max_width=1920, max_height=1920)
    sequence = fields.Integer(default=10)
    is_primary = fields.Boolean('Primary Photo')
```

## Routes

### Public Pages
| Route | Controller | Template |
|-------|-----------|----------|
| `/vehicles` | `VehicleController.catalog()` | `website_vehicle.catalog` |
| `/vehicles/<model>-<id>` | `VehicleController.detail()` | `website_vehicle.detail` |
| `/booking/request/<vehicle_id>` | `BookingController.request()` | `website_vehicle.booking_form` |

### Portal Pages (authenticated)
| Route | Controller | Template |
|-------|-----------|----------|
| `/my/rentals` | `PortalController.rentals()` | `website_vehicle.portal_rentals` |
| `/my/rentals/<id>` | `PortalController.rental_detail()` | `website_vehicle.portal_rental_detail` |

## Templates

### Catalog Page (`/vehicles`)
- Header with search/filter bar
- Grid of vehicle cards (3 columns desktop, 1 mobile)
- Each card: primary photo, name, category, "From X BWP/day"
- Filter: category, destination, price range

### Detail Page (`/vehicles/<id>-<slug>`)
- Photo gallery (main image + thumbnails)
- Vehicle info (model, year, seats, fuel type)
- Pricing table: destination × duration matrix
- Availability calendar (based on rental_status)
- "Book Now" CTA button

### Booking Form
- Customer info (auto-fill if logged in)
- Pickup/return dates
- Destination selection
- Price calculation (real-time)
- Terms acceptance checkbox
- Submit → creates `sale.order` in draft

## Security

### Public Access
- `/vehicles` — public (read published vehicles only)
- `/vehicles/<id>` — public (read published vehicles only)
- `/booking/*` — public (create only)

### Portal Access (authenticated)
- `/my/rentals` — portal user, own records only
- `/my/documents` — portal user, own uploads only

### Record Rules
```xml
<!-- Portal can see published vehicles -->
<record id="portal_vehicle_rule" model="ir.rule">
    <field name="name">Portal: Published Vehicles</field>
    <field name="model_id" ref="fleet.model_fleet_vehicle"/>
    <field name="domain_force">[('website_published', '=', True)]</field>
    <field name="groups" eval="[(4, ref('base.group_portal'))]"/>
</record>
```

## Social Media Integration

### Open Graph Meta Tags
```xml
<t t-call="website.layout">
    <t t-set="head_web">
        <meta property="og:title" t-att-content="vehicle.name"/>
        <meta property="og:description" t-att-content="vehicle.website_description"/>
        <meta property="og:image" t-att-content="vehicle.image_1920"/>
        <meta property="og:url" t-att-content="request.httprequest.url"/>
        <meta property="og:type" content="website"/>
    </t>
</t>
```

### Share Buttons
- Facebook Share
- WhatsApp Share
- Twitter/X Share
- Copy Link button

## Dependencies

- `website` module (Odoo standard)
- `website_portal` module (Odoo standard)
- `website_sale` module (optional, for cart integration)
