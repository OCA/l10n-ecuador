import logging
import pprint

import requests
from werkzeug import urls

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

PAYPHONE_URL = "https://pay.payphonetodoesposible.com/"


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("payphone", "Payphone")], ondelete={"payphone": "set default"}
    )
    payphone_access_token = fields.Char(
        required_if_provider="payphone",
        groups="base.group_system",
    )

    def _payphone_make_request(self, endpoint, payload):
        """Make a request to Payphone API at the specified endpoint.

        Note: self.ensure_one()

        :param str endpoint: The endpoint to be reached by the request.
        :param dict payload: The payload of the request.
        :return The JSON-formatted content of the response.
        :rtype: dict
        :raise ValidationError: If an HTTP error occurs.
        """
        self.ensure_one()
        url = urls.url_join(PAYPHONE_URL, f"api/{endpoint}")
        headers = {"Authorization": f"Bearer {self.payphone_access_token}"}
        response_content = {}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response_content = response.json()
            response.raise_for_status()
        except Exception:
            _logger.exception(
                "Invalid API request at %s with data:\n%s",
                url,
                pprint.pformat(payload),
            )
            message_list = []
            if response_content.get("message"):
                message_list.append(
                    f"Error Code: {response_content.get('errorCode')}. "
                    f"Descripcion: {response_content.get('message')}"
                )
            for messaje in response_content.get("errors", []):
                msj = messaje.get("message")
                msj_description = "".join(messaje.get("errorDescriptions"))
                message_list.append(
                    f"Error Code: {msj}. Descripcion: {msj_description}"
                )
            raise ValidationError(
                _(
                    "Payphone: The communication with the API failed. "
                    "Payphone gave us the following information: '%s'",
                    "\n".join(message_list),
                )
            ) from None
        return response_content
