# Optional Odoo Sign integration

Odoo Sign is an **Enterprise (OEEL-1)** application. This repository's main
module (`car_rental_management_odoo`) deliberately does **not** depend on it and
installs on Community.

## Available backends

| Backend | Where | Status |
|---|---|---|
| Private signing links (bearer token, drawn or checkbox acceptance) | `car_rental_management_odoo` | Always available; default |
| Odoo Sign | `car_rental_sign_bridge` (separate addon) | Only when Enterprise `sign` is installed |

The core module exposes a stateless gateway (`car.rental.sign.gateway`) that the
optional bridge overrides. Core code never imports `odoo.addons.sign` and never
declares a `sign.*` field, so the Community installation is unaffected.

## Enabling Odoo Sign

1. Install the Enterprise `sign` application.
2. Add this repository's `car_rental_sign_bridge` folder to your addons path.
3. Install **Car Rental - Odoo Sign Bridge**.
4. Open a generated agreement and use **Send with Odoo Sign** / **Refresh Sign Status**.

The signed PDF is copied into `car.rental.contract.completed_pdf` and the rental
agreement is marked signed; all existing print, invoice and access controls
continue to work unchanged.

## Compatibility notes

- Odoo 19 Sign uses `ir.attachment` → `sign.document` → `sign.template`; the
  bridge creates one immutable template per agreement version.
- v19 no longer has reusable `sign.item.role` records — signers are configured
  per template. The bridge maps the renter as the first signer.
- Verify exact field names on the target Enterprise database with `fields_get`;
  the bridge probes for `completed_file` / `completed_pdf`.
- Historical agreements are never migrated to Odoo Sign. They keep their
  private-link signatures, hashes and completed PDFs.

## Rollback

Switch back to private signing by uninstalling the bridge. Signed documents
remain in `completed_pdf` and all historical links stay intact.
