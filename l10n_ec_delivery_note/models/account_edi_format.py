from odoo import _, models


class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    def l10n_ec_is_required_for_delivery_note(self, note):
        if (
            note.country_code != "EC"
            or note.journal_id.l10n_ec_emission_type != "electronic"
        ):
            return False
        if (
            self.code == "l10n_ec_format_sri"
            and note.l10n_latam_internal_type.internal_type == "delivery_note"
        ):
            return True

    def _l10n_ec_check_delivery_note_configuration(self, document):
        if document.country_code == "EC":
            company = document.company_id
            partner = document.commercial_partner_id
            errors = self._l10n_ec_check_edi_configuration(document.journal_id, company)
            # ruc en transportista
            if not document.delivery_carrier_id.vat:
                errors.append(
                    _(
                        "You must set vat identification for carrier: %s",
                        document.delivery_carrier_id.name,
                    )
                )
            if not document.delivery_address_id.street:
                errors.append(
                    _(
                        "You must set delivery address for receiver: %s",
                        document.delivery_address_id.commercial_partner_id.name,
                    )
                )
            if not company.l10n_ec_delivery_note_version:
                errors.append(
                    _(
                        "You must set XML Version for Delivery Note company %s",
                        company.display_name,
                    )
                )
            error_identification = self._check_l10n_ec_values_identification_type(
                partner
            )
            if error_identification:
                errors.extend(error_identification)
        return errors

    def _check_l10n_ec_values_identification_type(self, partner):
        ec_ruc = self.env.ref("l10n_ec.ec_ruc", False)
        ec_dni = self.env.ref("l10n_ec.ec_dni", False)
        ec_passport = self.env.ref("l10n_ec.ec_passport", False)
        errors = []
        # validar que la empresa tenga ruc y tipo de documento
        if not partner.vat:
            errors.append(_("Please enter DNI/RUC to partner: %s", partner.name))
        if partner.l10n_latam_identification_type_id.id not in (
            ec_ruc.id,
            ec_dni.id,
            ec_passport.id,
        ):
            errors.append(
                _(
                    "You must set Identification type as RUC, DNI or Passport "
                    "for ecuadorian company, on partner %s",
                    partner.name,
                )
            )
        return errors
