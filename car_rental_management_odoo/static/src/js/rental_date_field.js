/** @odoo-module **/

import { formatDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import {
    DateTimeField,
    dateField,
} from "@web/views/fields/datetime/datetime_field";

class RentalFullDateField extends DateTimeField {
    getFormattedValue(valueIndex, numeric = this.props.numeric) {
        const value = this.values[valueIndex];
        if (this.field.type === "date") {
            return formatDate(value, { format: "d MMMM yyyy" });
        }
        return super.getFormattedValue(valueIndex, numeric);
    }
}

registry.category("fields").add("rental_full_date", {
    ...dateField,
    component: RentalFullDateField,
});
