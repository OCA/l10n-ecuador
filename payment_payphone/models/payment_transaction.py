import logging

from werkzeug import urls

from odoo import _, models
from odoo.exceptions import ValidationError

from ..controllers.main import PayphoneController

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _get_specific_rendering_values(self, processing_values):
        """Override of `payment` to return Payphone-specific rendering values.
        :param dict processing_values:
            The generic and specific processing values of the transaction
        :return: The dict of provider-specific processing values.
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != "payphone":
            return res

        # Initiate the payment and retrieve the payment link data.
        payload = self._payphone_prepare_preference_request_payload()
        payphone_response = self.provider_id._payphone_make_request(
            "button/Prepare", payload=payload
        )

        # Extract the payment link URL and params and embed them in the redirect form.
        self.write({"provider_reference": payphone_response.get("paymentId")})
        api_url = payphone_response.get("payWithPayPhone")
        parsed_url = urls.url_parse(api_url)
        url_params = urls.url_decode(parsed_url.query)
        rendering_values = {
            "api_url": api_url,
            "url_params": url_params,  # Encore the params as inputs to preserve them.
        }
        return rendering_values

    def _payphone_prepare_preference_request_payload(self):
        """Create the payload for the preference request
        based on the transaction values.

        :return: The request payload.
        :rtype: dict
        """
        base_url = self.provider_id.get_base_url()
        return_url = urls.url_join(base_url, PayphoneController._return_url)
        return {
            "amount": int(self.amount * 100),
            "AmountWithoutTax": int(self.amount * 100),
            "currency": "USD",
            "clientTransactionId": self.reference,
            "reference": self.reference,
            "ResponseUrl": return_url,
            "cancellationUrl": return_url,
        }

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """Override of `payment` to find the transaction based on Payphone data.

        :param str provider_code: The code of the provider that handled the transaction.
        :param dict notification_data: The notification data sent by the provider.
        :return: The transaction if found.
        :rtype: recordset of `payment.transaction`
        :raise ValidationError: If inconsistent data were received.
        :raise ValidationError: If the data match no transaction.
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != "payphone" or len(tx) == 1:
            return tx

        reference = notification_data.get("clientTransactionId")
        if not reference:
            raise ValidationError(_("Payphone: Received data with missing reference."))

        tx = self.search(
            [("reference", "=", reference), ("provider_code", "=", "payphone")]
        )
        if not tx:
            raise ValidationError(
                _("Payphone: No transaction found matching reference %s.", reference)
            )
        return tx

    def _process_notification_data(self, notification_data):
        """Override of `payment` to process the transaction based on Payphone data.

        Note: self.ensure_one() from `_process_notification_data`

        :param dict notification_data: The notification data sent by the provider.
        :return: None
        :raise ValidationError: If inconsistent data were received.
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != "payphone":
            return

        if notification_data.get("id") == "0":
            self._set_canceled()
            return
        if (
            "id" not in notification_data
            and "Su dominio no está autorizado" in notification_data.get("msg", "")
        ):
            self._set_error(notification_data.get("msg", ""))
            return
        payload = {
            "id": notification_data.get("id"),
            "clientTxId": notification_data.get("clientTransactionId"),
        }
        # Verify the notification data.
        verified_payment_data = self.provider_id._payphone_make_request(
            "button/V2/Confirm", payload=payload
        )

        # Update the payment method.
        payment_status = verified_payment_data.get("statusCode")
        if payment_status == 3:
            self._set_done()
        elif payment_status == 2:
            self._set_canceled()
        else:  # Classify unsupported payment status as the `error` tx state.
            _logger.warning(
                "Received data for transaction "
                "with reference %s with invalid payment status: %s",
                self.reference,
                payment_status,
            )
            self._set_error(
                "Payphone: "
                + _("Received data with invalid status: %s", payment_status)
            )
